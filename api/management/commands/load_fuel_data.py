import csv
import time
import requests
import logging
from collections import defaultdict
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from api.models import FuelStop

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "FuelRoutePlanner/1.0"}


def geocode_city_state(city, state, cache):
    key = (city.strip().lower(), state.strip().upper())
    if key in cache:
        return cache[key]
    params = {
        "q": f"{city.strip()}, {state.strip()}, USA",
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = (float(data[0]["lat"]), float(data[0]["lon"])) if data else (None, None)
    except Exception as e:
        logger.warning(f"Geocode failed for {city}, {state}: {e}")
        result = (None, None)
    cache[key] = result
    time.sleep(1.1)
    return result


class Command(BaseCommand):
    help = "Load fuel prices CSV into the database."

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str, help="Path to the fuel prices CSV file")
        parser.add_argument('--no-geocode', action='store_true', help="Skip geocoding")

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        skip_geocode = options['no_geocode']

        self.stdout.write(f"Reading CSV: {csv_path}")

        stop_data = defaultdict(lambda: {
            'name': '', 'address': '', 'city': '',
            'state': '', 'rack_id': None, 'prices': [],
        })

        try:
            with open(csv_path, newline='', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    opis_id = int(row['OPIS Truckstop ID'])
                    try:
                        price = float(row['Retail Price'].strip())
                    except ValueError:
                        continue
                    d = stop_data[opis_id]
                    d['name'] = row['Truckstop Name'].strip()
                    d['address'] = row['Address'].strip()
                    d['city'] = row['City'].strip()
                    d['state'] = row['State'].strip()
                    try:
                        d['rack_id'] = int(row['Rack ID'])
                    except (ValueError, KeyError):
                        pass
                    d['prices'].append(price)
        except FileNotFoundError:
            raise CommandError(f"CSV file not found: {csv_path}")

        self.stdout.write(f"Found {len(stop_data)} unique fuel stops")

        geo_cache = {}
        if not skip_geocode:
            unique_locations = {(d['city'], d['state']) for d in stop_data.values()}
            self.stdout.write(f"Geocoding {len(unique_locations)} city/state pairs...")
            for i, (city, state) in enumerate(unique_locations, 1):
                geocode_city_state(city, state, geo_cache)
                if i % 25 == 0:
                    self.stdout.write(f"  Geocoded {i}/{len(unique_locations)}...")

        FuelStop.objects.all().delete()
        self.stdout.write("Cleared existing fuel stops.")

        to_create = []
        for opis_id, d in stop_data.items():
            avg_price = sum(d['prices']) / len(d['prices'])
            lat, lon = (None, None)
            if not skip_geocode:
                lat, lon = geo_cache.get(
                    (d['city'].lower(), d['state'].upper()), (None, None)
                )
            to_create.append(FuelStop(
                opis_id=opis_id,
                name=d['name'],
                address=d['address'],
                city=d['city'],
                state=d['state'],
                rack_id=d['rack_id'],
                retail_price=round(avg_price, 6),
                latitude=lat,
                longitude=lon,
            ))

        with transaction.atomic():
            FuelStop.objects.bulk_create(to_create, batch_size=500)

        geo_count = sum(1 for s in to_create if s.latitude is not None)
        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(to_create)} fuel stops ({geo_count} geocoded)!"
        ))