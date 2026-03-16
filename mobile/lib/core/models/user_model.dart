class UserModel {
  final int id;
  final String email;
  final String fullName;
  final String role;
  final int? pUserId;

  const UserModel({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    this.pUserId,
  });

  factory UserModel.fromJson(Map<String, dynamic> json) => UserModel(
        id: json['id'] as int,
        email: json['email'] as String,
        fullName: json['full_name'] as String,
        role: json['role'] as String,
        pUserId: json['p_user_id'] as int?,
      );

  bool get isAdmin => role == 'admin';
  bool get isKoordinator => role == 'koordinator' || isAdmin;
  bool get isSupervisor => role == 'supervisor' || isKoordinator;
  bool get isTechnician => role == 'technician';

  String get displayName {
    final parts = fullName.split(' ');
    return parts.length > 1 ? '${parts[0]} ${parts[1]}' : fullName;
  }

  String get roleLabel {
    switch (role) {
      case 'admin':
        return 'Administrator';
      case 'koordinator':
        return 'Koordinator';
      case 'supervisor':
        return 'Supervisor';
      case 'technician':
        return 'Teknisi';
      default:
        return role;
    }
  }
}
