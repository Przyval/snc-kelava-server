import 'dart:io';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import 'package:image_picker/image_picker.dart';
import '../providers/visit_provider.dart';
import '../../../core/models/visit_model.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/services/location_service.dart';

class VisitDetailScreen extends StatefulWidget {
  final VisitModel visit;
  const VisitDetailScreen({super.key, required this.visit});

  @override
  State<VisitDetailScreen> createState() => _VisitDetailScreenState();
}

class _VisitDetailScreenState extends State<VisitDetailScreen> {
  final _remarksCtrl = TextEditingController();
  final _imagePicker = ImagePicker();
  final List<XFile> _photos = [];

  bool _submitting = false;
  bool _fetchingLocation = false;
  LocationResult? _location;

  @override
  void dispose() {
    _remarksCtrl.dispose();
    super.dispose();
  }

  // ── GPS ────────────────────────────────────────────────

  Future<void> _captureLocation() async {
    setState(() => _fetchingLocation = true);
    final loc = await LocationService.instance.getCurrentLocation();
    if (!mounted) return;
    setState(() {
      _location = loc;
      _fetchingLocation = false;
    });
    if (loc == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Tidak dapat mengambil lokasi. Pastikan GPS aktif.'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  // ── Photos ─────────────────────────────────────────────

  Future<void> _takePhoto() async {
    final photo = await _imagePicker.pickImage(
      source: ImageSource.camera,
      maxWidth: 1280,
      maxHeight: 1280,
      imageQuality: 80,
    );
    if (photo != null) setState(() => _photos.add(photo));
  }

  Future<void> _pickFromGallery() async {
    final photos = await _imagePicker.pickMultiImage(
      maxWidth: 1280,
      maxHeight: 1280,
      imageQuality: 80,
    );
    if (photos.isNotEmpty) setState(() => _photos.addAll(photos));
  }

  void _removePhoto(int index) {
    setState(() => _photos.removeAt(index));
  }

  // ── Check-in ──────────────────────────────────────────

  Future<void> _checkIn() async {
    // 1. Capture GPS first
    if (_location == null) {
      await _captureLocation();
      if (_location == null && mounted) {
        // Proceed without GPS — server logs it as null
        final proceed = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text('GPS Tidak Tersedia'),
            content: const Text(
                'Lokasi tidak dapat diambil. Lanjutkan check-in tanpa GPS?'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Batal')),
              ElevatedButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  child: const Text('Lanjutkan')),
            ],
          ),
        );
        if (proceed != true) return;
      }
    }

    setState(() => _submitting = true);
    final ok = await context.read<VisitProvider>().checkIn(
          widget.visit.id,
          lat: _location?.latitude,
          lng: _location?.longitude,
          photos: _photos,
        );
    if (!mounted) return;
    setState(() => _submitting = false);

    if (ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Check-in berhasil!'),
          backgroundColor: AppColors.success,
          behavior: SnackBarBehavior.floating,
        ),
      );
      Navigator.pop(context);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Gagal check-in. Coba lagi.'),
          backgroundColor: AppColors.error,
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  // ── Check-out ─────────────────────────────────────────

  Future<void> _checkOut() async {
    if (_remarksCtrl.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Catatan kunjungan wajib diisi'),
          behavior: SnackBarBehavior.floating,
        ),
      );
      return;
    }

    // Capture GPS
    if (_location == null) await _captureLocation();

    setState(() => _submitting = true);
    final ok = await context.read<VisitProvider>().checkOut(
          widget.visit.id,
          _remarksCtrl.text.trim(),
          lat: _location?.latitude,
          lng: _location?.longitude,
          photos: _photos,
        );
    if (!mounted) return;
    setState(() => _submitting = false);

    if (ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Check-out berhasil!'),
          backgroundColor: AppColors.success,
          behavior: SnackBarBehavior.floating,
        ),
      );
      Navigator.pop(context);
    }
  }

  // ── Build ─────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final visit = widget.visit;
    return Scaffold(
      appBar: AppBar(title: Text(visit.customerName)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _StatusBanner(visit: visit),
            const SizedBox(height: 20),

            // Info card
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Detail Kunjungan',
                        style: TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 14,
                            color: AppColors.textPrimary)),
                    const SizedBox(height: 12),
                    if (visit.customerAddress != null)
                      _InfoRow(
                          icon: Icons.location_on_outlined,
                          label: 'Alamat',
                          value: visit.customerAddress!),
                    if (visit.kontrakNo != null)
                      _InfoRow(
                          icon: Icons.description_outlined,
                          label: 'No. Kontrak',
                          value: visit.kontrakNo!),
                    if (visit.visitType != null)
                      _InfoRow(
                          icon: Icons.category_outlined,
                          label: 'Tipe',
                          value: visit.visitType!),
                    if (visit.checkIn != null)
                      _InfoRow(
                          icon: Icons.login_rounded,
                          label: 'Check In',
                          value:
                              DateFormat('HH:mm, d MMM').format(visit.checkIn!)),
                    if (visit.checkOut != null)
                      _InfoRow(
                          icon: Icons.logout_rounded,
                          label: 'Check Out',
                          value: DateFormat('HH:mm, d MMM')
                              .format(visit.checkOut!)),
                  ],
                ),
              ),
            ),

            // Action area — only if visit is still actionable
            if (visit.canCheckIn || visit.canCheckOut) ...[
              const SizedBox(height: 20),

              // ── GPS Section ──
              _GpsCard(
                location: _location,
                fetching: _fetchingLocation,
                onCapture: _captureLocation,
              ),
              const SizedBox(height: 16),

              // ── Photo Section ──
              _PhotoSection(
                photos: _photos,
                onTakePhoto: _takePhoto,
                onPickGallery: _pickFromGallery,
                onRemove: _removePhoto,
              ),
              const SizedBox(height: 16),

              // ── Remarks (checkout only) ──
              if (visit.canCheckOut) ...[
                TextFormField(
                  controller: _remarksCtrl,
                  maxLines: 3,
                  decoration: const InputDecoration(
                    labelText: 'Catatan Kunjungan *',
                    hintText: 'Deskripsikan pekerjaan yang dilakukan...',
                    alignLabelWithHint: true,
                  ),
                ),
                const SizedBox(height: 16),
              ],

              // ── Action Button ──
              SizedBox(
                height: 52,
                child: ElevatedButton.icon(
                  onPressed: _submitting
                      ? null
                      : (visit.canCheckIn ? _checkIn : _checkOut),
                  style: ElevatedButton.styleFrom(
                    backgroundColor:
                        visit.canCheckIn ? AppColors.success : AppColors.error,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                  ),
                  icon: _submitting
                      ? const SizedBox.shrink()
                      : Icon(
                          visit.canCheckIn
                              ? Icons.login_rounded
                              : Icons.logout_rounded,
                          color: Colors.white,
                        ),
                  label: _submitting
                      ? const SizedBox(
                          width: 22,
                          height: 22,
                          child: CircularProgressIndicator(
                              color: Colors.white, strokeWidth: 2),
                        )
                      : Text(
                          visit.canCheckIn ? 'Check In Sekarang' : 'Check Out',
                          style: const TextStyle(
                              color: Colors.white,
                              fontSize: 16,
                              fontWeight: FontWeight.w600),
                        ),
                ),
              ),
              const SizedBox(height: 24),
            ],
          ],
        ),
      ),
    );
  }
}

// ── GPS Card Widget ─────────────────────────────────────

class _GpsCard extends StatelessWidget {
  final LocationResult? location;
  final bool fetching;
  final VoidCallback onCapture;

  const _GpsCard({
    required this.location,
    required this.fetching,
    required this.onCapture,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  location != null
                      ? Icons.gps_fixed_rounded
                      : Icons.gps_not_fixed_rounded,
                  color: location != null
                      ? AppColors.success
                      : AppColors.textSecondary,
                  size: 20,
                ),
                const SizedBox(width: 8),
                const Text('Lokasi GPS',
                    style: TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 14,
                        color: AppColors.textPrimary)),
                const Spacer(),
                if (fetching)
                  const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                else
                  TextButton.icon(
                    onPressed: onCapture,
                    icon: const Icon(Icons.my_location_rounded, size: 16),
                    label: Text(location != null ? 'Refresh' : 'Ambil Lokasi'),
                  ),
              ],
            ),
            if (location != null) ...[
              const SizedBox(height: 8),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: AppColors.success.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.check_circle_rounded,
                        color: AppColors.success, size: 16),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '${location!.latitude.toStringAsFixed(6)}, ${location!.longitude.toStringAsFixed(6)}\n'
                        'Akurasi: ${location!.accuracy.toStringAsFixed(0)}m',
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.textPrimary),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ── Photo Section Widget ────────────────────────────────

class _PhotoSection extends StatelessWidget {
  final List<XFile> photos;
  final VoidCallback onTakePhoto;
  final VoidCallback onPickGallery;
  final ValueChanged<int> onRemove;

  const _PhotoSection({
    required this.photos,
    required this.onTakePhoto,
    required this.onPickGallery,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.camera_alt_outlined,
                    color: AppColors.primary, size: 20),
                const SizedBox(width: 8),
                Text(
                  'Foto Bukti (${photos.length})',
                  style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 14,
                      color: AppColors.textPrimary),
                ),
              ],
            ),
            const SizedBox(height: 12),

            // Photo grid
            if (photos.isNotEmpty) ...[
              SizedBox(
                height: 90,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: photos.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (ctx, i) => Stack(
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Image.file(
                          File(photos[i].path),
                          width: 90,
                          height: 90,
                          fit: BoxFit.cover,
                        ),
                      ),
                      Positioned(
                        top: 2,
                        right: 2,
                        child: GestureDetector(
                          onTap: () => onRemove(i),
                          child: Container(
                            decoration: const BoxDecoration(
                              color: AppColors.error,
                              shape: BoxShape.circle,
                            ),
                            padding: const EdgeInsets.all(4),
                            child: const Icon(Icons.close,
                                color: Colors.white, size: 14),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
            ],

            // Buttons
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onTakePhoto,
                    icon: const Icon(Icons.camera_alt_rounded, size: 18),
                    label: const Text('Kamera'),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onPickGallery,
                    icon: const Icon(Icons.photo_library_rounded, size: 18),
                    label: const Text('Galeri'),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

// ── Status Banner ───────────────────────────────────────

class _StatusBanner extends StatelessWidget {
  final VisitModel visit;
  const _StatusBanner({required this.visit});

  @override
  Widget build(BuildContext context) {
    Color color;
    String label;
    IconData icon;
    if (visit.isCompleted) {
      color = AppColors.success;
      label = 'Kunjungan Selesai';
      icon = Icons.check_circle_rounded;
    } else if (visit.isCheckedIn) {
      color = AppColors.warning;
      label = 'Sedang Berlangsung';
      icon = Icons.radio_button_checked_rounded;
    } else {
      color = AppColors.primary;
      label = 'Belum Check In';
      icon = Icons.schedule_rounded;
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(width: 12),
          Text(label,
              style: TextStyle(
                  color: color, fontWeight: FontWeight.w700, fontSize: 15)),
        ],
      ),
    );
  }
}

// ── Info Row ────────────────────────────────────────────

class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  const _InfoRow(
      {required this.icon, required this.label, required this.value});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 16, color: AppColors.textSecondary),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label,
                      style: const TextStyle(
                          fontSize: 11, color: AppColors.textSecondary)),
                  Text(value,
                      style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textPrimary)),
                ],
              ),
            ),
          ],
        ),
      );
}
