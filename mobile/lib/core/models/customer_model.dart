class CustomerModel {
  final int id;
  final String code;
  final String name;
  final String? address;
  final String? phone;
  final String? contactPerson;
  final String? segment;
  final String? status;
  final int? totalVisits;
  final DateTime? lastVisit;

  const CustomerModel({
    required this.id,
    required this.code,
    required this.name,
    this.address,
    this.phone,
    this.contactPerson,
    this.segment,
    this.status,
    this.totalVisits,
    this.lastVisit,
  });

  factory CustomerModel.fromJson(Map<String, dynamic> json) => CustomerModel(
        id: json['id'] as int,
        code: json['code'] as String? ?? '',
        name: json['name'] as String? ?? '-',
        address: json['address'] as String?,
        phone: json['phone'] as String?,
        contactPerson: json['contact_person'] as String?,
        segment: json['segment'] as String?,
        status: json['status'] as String?,
        totalVisits: json['total_visits'] as int?,
        lastVisit: json['last_visit'] != null
            ? DateTime.tryParse(json['last_visit'])
            : null,
      );

  String get initials {
    final parts = name.split(' ').where((p) => p.isNotEmpty).toList();
    if (parts.isEmpty) return '?';
    if (parts.length == 1) return parts[0][0].toUpperCase();
    return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
  }
}
