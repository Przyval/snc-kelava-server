class CustomerModel {
  final int id;
  final String code;
  final String name;
  final String? address;
  final String? city;
  final String? province;
  final String? phone;
  final String? email;
  final String? contactPerson;
  final String? contactPersonPhone;
  final String? segment;
  final String? status;
  final String source; // 'kelava' | 'snc'
  final int? totalVisits;
  final DateTime? lastVisit;

  const CustomerModel({
    required this.id,
    required this.code,
    required this.name,
    required this.source,
    this.address,
    this.city,
    this.province,
    this.phone,
    this.email,
    this.contactPerson,
    this.contactPersonPhone,
    this.segment,
    this.status,
    this.totalVisits,
    this.lastVisit,
  });

  factory CustomerModel.fromJson(Map<String, dynamic> json) => CustomerModel(
        id: json['id'] as int,
        code: json['code'] as String? ?? '',
        name: json['name'] as String? ?? '-',
        source: json['source'] as String? ?? 'kelava',
        address: json['address'] as String?,
        city: json['new_city'] as String?,
        province: json['new_province'] as String?,
        phone: (json['phone1'] ?? json['phone']) as String?,
        email: json['email'] as String?,
        contactPerson:
            (json['contact_person_name'] ?? json['contact_person']) as String?,
        contactPersonPhone: json['contact_person_phone'] as String?,
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

  bool get isSNC => source == 'snc';
}
