import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .utils import (
    geocode_location,
    get_route,
    find_optimal_fuel_stops,
    calculate_total_cost,
)

logger = logging.getLogger(__name__)


class RoutePlannerView(APIView):
    def post(self, request):
        start_input = request.data.get('start', '').strip()
        finish_input = request.data.get('finish', '').strip()

        if not start_input or not finish_input:
            return Response(
                {"error": "Both 'start' and 'finish' fields are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            start_lat, start_lon = geocode_location(start_input)
            finish_lat, finish_lon = geocode_location(finish_input)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            route = get_route(
                (start_lat, start_lon),
                (finish_lat, finish_lon)
            )
        except Exception as e:
            logger.exception("Route fetch failed")
            return Response(
                {"error": f"Could not compute route: {e}"},
                status=status.HTTP_502_BAD_GATEWAY
            )

        distance_miles = route['distance_miles']
        waypoints = route['waypoints']

        fuel_stops = find_optimal_fuel_stops(waypoints, distance_miles)
        total_cost = calculate_total_cost(fuel_stops, distance_miles)
        total_gallons = round(distance_miles / 10, 2)

        return Response({
            "start": {
                "input": start_input,
                "latitude": start_lat,
                "longitude": start_lon,
            },
            "finish": {
                "input": finish_input,
                "latitude": finish_lat,
                "longitude": finish_lon,
            },
            "route": {
                "distance_miles": distance_miles,
                "duration_hours": round(route['duration_seconds'] / 3600, 1),
                "geometry": route['geometry'],
                "note": route.get('note', ''),
            },
            "fuel_stops": fuel_stops,
            "summary": {
                "total_stops": len(fuel_stops),
                "total_miles": distance_miles,
                "total_gallons": total_gallons,
                "total_fuel_cost_usd": total_cost,
                "vehicle_range_miles": 500,
                "vehicle_mpg": 10,
            },
        }, status=status.HTTP_200_OK)


class FuelStopsListView(APIView):
    def get(self, request):
        from .models import FuelStop
        qs = FuelStop.objects.all()

        state = request.query_params.get('state')
        max_price = request.query_params.get('max_price')

        if state:
            qs = qs.filter(state__iexact=state)
        if max_price:
            try:
                qs = qs.filter(retail_price__lte=float(max_price))
            except ValueError:
                return Response({"error": "max_price must be a number."}, status=400)

        qs = qs.order_by('retail_price')[:100]
        data = list(qs.values(
            'opis_id', 'name', 'city', 'state', 'address',
            'retail_price', 'latitude', 'longitude'
        ))
        return Response({"count": len(data), "results": data})