class VisitModel {
  final int id;
  final int? roadPlanId;
  final String customerName;
  final String? customerAddress;
  final String? kontrakNo;
  final String status;
  final DateTime? scheduledDate;
  final DateTime? checkIn;
  final DateTime? checkOut;
  final double? latitude;
  final double? longitude;
  final String? remarks;
  final String? visitType;

  const VisitModel({
    required this.id,
    this.roadPlanId,
    required this.customerName,
    this.customerAddress,
    this.kontrakNo,
    required this.status,
    this.scheduledDate,
    this.checkIn,
    this.checkOut,
    this.latitude,
    this.longitude,
    this.remarks,
    this.visitType,
  });

  factory VisitModel.fromJson(Map<String, dynamic> json) => VisitModel(
        id: json['id'] as int,
        roadPlanId: json['road_plan_id'] as int?,
        customerName: json['customer_name'] as String? ?? '-',
        customerAddress: json['customer_address'] as String?,
        kontrakNo: json['kontrak_no'] as String?,
        status: json['status'] as String? ?? 'SCHEDULED',
        scheduledDate: json['scheduled_date'] != null
            ? DateTime.tryParse(json['scheduled_date'])
            : null,
        checkIn: json['check_in'] != null
            ? DateTime.tryParse(json['check_in'])
            : null,
        checkOut: json['check_out'] != null
            ? DateTime.tryParse(json['check_out'])
            : null,
        latitude: (json['latitude'] as num?)?.toDouble(),
        longitude: (json['longitude'] as num?)?.toDouble(),
        remarks: json['remarks'] as String?,
        visitType: json['visit_type'] as String?,
      );

  bool get isCheckedIn => checkIn != null;
  bool get isCompleted => checkOut != null;
  bool get canCheckIn => !isCheckedIn;
  bool get canCheckOut => isCheckedIn && !isCompleted;

  String get statusLabel {
    if (isCompleted) return 'Selesai';
    if (isCheckedIn) return 'Sedang Berlangsung';
    return 'Terjadwal';
  }
}
