import 'package:geolocator/geolocator.dart';
import 'package:permission_handler/permission_handler.dart';

class LocationResult {
  final double latitude;
  final double longitude;
  final double accuracy;
  final DateTime timestamp;

  const LocationResult({
    required this.latitude,
    required this.longitude,
    required this.accuracy,
    required this.timestamp,
  });

  Map<String, dynamic> toJson() => {
        'latitude': latitude,
        'longitude': longitude,
        'accuracy': accuracy,
      };
}

class LocationService {
  LocationService._();
  static final instance = LocationService._();

  /// Request location permission and return current position.
  /// Returns null if permission denied or location unavailable.
  Future<LocationResult?> getCurrentLocation() async {
    // 1. Check if location services are enabled
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) return null;

    // 2. Check / request permission
    var status = await Permission.locationWhenInUse.status;
    if (status.isDenied) {
      status = await Permission.locationWhenInUse.request();
    }
    if (!status.isGranted) return null;

    // 3. Get position with timeout
    try {
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 15),
        ),
      );
      return LocationResult(
        latitude: pos.latitude,
        longitude: pos.longitude,
        accuracy: pos.accuracy,
        timestamp: pos.timestamp,
      );
    } catch (_) {
      return null;
    }
  }

  /// Calculate distance in meters between two coordinates.
  double distanceBetween(
    double lat1,
    double lng1,
    double lat2,
    double lng2,
  ) {
    return Geolocator.distanceBetween(lat1, lng1, lat2, lng2);
  }

  /// Check if technician is within acceptable radius of customer location.
  /// Returns true if within [radiusMeters] (default 500m).
  bool isWithinRadius({
    required double techLat,
    required double techLng,
    required double customerLat,
    required double customerLng,
    double radiusMeters = 500,
  }) {
    final distance = distanceBetween(techLat, techLng, customerLat, customerLng);
    return distance <= radiusMeters;
  }
}
