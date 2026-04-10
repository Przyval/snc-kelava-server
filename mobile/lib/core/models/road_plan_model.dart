class RoadPlanModel {
  final int id;
  final String source; // 'kelava' | 'snc'
  final int pUserId;
  final int customerId;
  final int? kontrakId;
  final String customerName;
  final String? customerAddress;
  final String technicianName;
  final String? kontrakNo;
  final String status;
  final bool isCancel;
  final DateTime visitDate;
  final String? title;
  final String? remarks;
  final String? visitType;
  final String? noRa;

  const RoadPlanModel({
    required this.id,
    required this.source,
    required this.pUserId,
    required this.customerId,
    this.kontrakId,
    required this.customerName,
    this.customerAddress,
    required this.technicianName,
    this.kontrakNo,
    required this.status,
    required this.isCancel,
    required this.visitDate,
    this.title,
    this.remarks,
    this.visitType,
    this.noRa,
  });

  factory RoadPlanModel.fromJson(Map<String, dynamic> json) => RoadPlanModel(
        id: json['id'] as int,
        source: json['source'] as String? ?? 'kelava',
        pUserId: (json['p_user_id'] ?? json['id_user']) as int,
        customerId: (json['customer_id'] ?? json['id_customer']) as int,
        kontrakId: json['kontrak_id'] as int? ?? json['id_kontrak'] as int?,
        customerName: json['customer_name'] as String? ?? '-',
        customerAddress: json['customer_address'] as String?,
        technicianName: json['technician_name'] as String? ?? '-',
        kontrakNo: json['kontrak_no'] as String? ?? json['no_kontrak'] as String?,
        status: json['status'] as String? ?? 'Baru',
        isCancel: json['is_cancel'] as bool? ?? false,
        visitDate: DateTime.parse(
          json['visit_date'] as String? ?? DateTime.now().toIso8601String(),
        ),
        title: json['title'] as String?,
        remarks: json['remarks'] as String?,
        visitType: json['visit_type'] as String?,
        noRa: json['no_ra'] as String?,
      );

  bool get isCompleted => status == 'Selesai';
  bool get isInProgress => status == 'Berjalan';
  bool get isNew => status == 'Baru';

  String get statusLabel => switch (status) {
        'Selesai' => 'Selesai',
        'Berjalan' => 'Berlangsung',
        'Baru' => 'Terjadwal',
        'Requested' => 'Menunggu',
        'Cancelled' => 'Dibatalkan',
        _ => status,
      };
}
