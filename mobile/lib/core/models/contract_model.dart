class ContractModel {
  final int id;
  final String noKontrak;
  final String? startDate;
  final String? endDate;
  final String isActive;
  final int? daysRemaining;
  final double? nilaiKontrak;
  final int? frekuensiVisit;
  final String? notes;
  final int? customerId;
  final String? customerName;
  final String? customerCity;
  final String source; // 'kelava' | 'snc'

  const ContractModel({
    required this.id,
    required this.noKontrak,
    required this.isActive,
    required this.source,
    this.startDate,
    this.endDate,
    this.daysRemaining,
    this.nilaiKontrak,
    this.frekuensiVisit,
    this.notes,
    this.customerId,
    this.customerName,
    this.customerCity,
  });

  factory ContractModel.fromJson(Map<String, dynamic> json) => ContractModel(
        id: json['id'] as int,
        noKontrak: json['no_kontrak'] as String? ?? '-',
        isActive: json['is_active'] as String? ?? 'NO',
        source: json['source'] as String? ?? 'kelava',
        startDate: json['start_date'] as String?,
        endDate: json['end_date'] as String?,
        daysRemaining: _parseInt(json['days_remaining']),
        nilaiKontrak: _parseDouble(json['nilai_kontrak']),
        frekuensiVisit: _parseInt(json['frekuensi_visit']),
        notes: json['notes'] as String?,
        customerId:
            (json['customer_id'] ?? json['snc_customer_id']) as int?,
        customerName: json['customer_name'] as String?,
        customerCity: json['new_city'] as String?,
      );

  bool get isActiveContract => isActive == 'YES';
  bool get isSNC => source == 'snc';

  bool get isExpiringSoon =>
      daysRemaining != null && daysRemaining! >= 0 && daysRemaining! <= 30;
  bool get isExpired => daysRemaining != null && daysRemaining! < 0;

  static int? _parseInt(dynamic v) {
    if (v == null) return null;
    if (v is int) return v;
    return int.tryParse(v.toString());
  }

  static double? _parseDouble(dynamic v) {
    if (v == null) return null;
    if (v is double) return v;
    if (v is int) return v.toDouble();
    return double.tryParse(v.toString());
  }
}
