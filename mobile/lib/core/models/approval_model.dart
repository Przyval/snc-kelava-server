class ApprovalModel {
  final int id;
  final String actionType;
  final String status;
  final String? technicianName;
  final String? customerName;
  final String? description;
  final String? createdBy;
  final DateTime? createdAt;
  final String? scheduledDate;

  const ApprovalModel({
    required this.id,
    required this.actionType,
    required this.status,
    this.technicianName,
    this.customerName,
    this.description,
    this.createdBy,
    this.createdAt,
    this.scheduledDate,
  });

  factory ApprovalModel.fromJson(Map<String, dynamic> json) => ApprovalModel(
        id: json['id'] as int,
        actionType: json['action_type'] as String? ?? '',
        status: json['status'] as String? ?? 'PENDING_APPROVAL',
        technicianName: json['technician_name'] as String?,
        customerName: json['customer_name'] as String?,
        description: json['description'] as String?,
        createdBy: json['created_by_name'] as String?,
        createdAt: json['created_at'] != null
            ? DateTime.tryParse(json['created_at'])
            : null,
        scheduledDate: json['scheduled_date'] as String?,
      );

  String get actionTypeLabel {
    switch (actionType) {
      case 'SIDAK':
        return 'Sidak';
      case 'SP_WARNING':
        return 'Surat Peringatan';
      case 'COACHING':
        return 'Coaching';
      default:
        return actionType;
    }
  }
}
