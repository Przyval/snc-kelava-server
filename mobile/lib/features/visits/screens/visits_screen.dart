import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/visit_provider.dart';
import '../../../core/models/visit_model.dart';
import '../../../core/theme/app_theme.dart';
import 'visit_detail_screen.dart';

class VisitsScreen extends StatefulWidget {
  const VisitsScreen({super.key});

  @override
  State<VisitsScreen> createState() => _VisitsScreenState();
}

class _VisitsScreenState extends State<VisitsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<VisitProvider>().loadToday();
    });
  }

  @override
  Widget build(BuildContext context) {
    final prov = context.watch<VisitProvider>();
    final today = DateFormat('EEEE, d MMMM yyyy', 'id').format(DateTime.now());

    return Scaffold(
      appBar: AppBar(
        title: const Text('Aktivitas'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<VisitProvider>().loadToday(),
          ),
        ],
      ),
      body: Column(
        children: [
          // Date banner
          Container(
            color: AppColors.primary,
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
            child: Text(
              today,
              style: const TextStyle(color: Colors.white70, fontSize: 13),
            ),
          ),
          Expanded(
            child: prov.loading
                ? const Center(child: CircularProgressIndicator())
                : prov.visits.isEmpty
                    ? _EmptyVisits()
                    : RefreshIndicator(
                        onRefresh: () => context.read<VisitProvider>().loadToday(),
                        child: ListView.separated(
                          padding: const EdgeInsets.all(16),
                          itemCount: prov.visits.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 10),
                          itemBuilder: (ctx, i) =>
                              _VisitCard(visit: prov.visits[i]),
                        ),
                      ),
          ),
        ],
      ),
    );
  }
}

class _VisitCard extends StatelessWidget {
  final VisitModel visit;
  const _VisitCard({required this.visit});

  @override
  Widget build(BuildContext context) {
    Color statusColor;
    IconData statusIcon;
    if (visit.isCompleted) {
      statusColor = AppColors.success;
      statusIcon = Icons.check_circle_rounded;
    } else if (visit.isCheckedIn) {
      statusColor = AppColors.warning;
      statusIcon = Icons.radio_button_checked_rounded;
    } else {
      statusColor = AppColors.textSecondary;
      statusIcon = Icons.schedule_rounded;
    }

    return GestureDetector(
      onTap: () => Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => VisitDetailScreen(visit: visit),
        ),
      ),
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          boxShadow: const [BoxShadow(color: AppColors.cardShadow, blurRadius: 6)],
          border: visit.isCheckedIn && !visit.isCompleted
              ? Border.all(color: AppColors.warning, width: 1.5)
              : null,
        ),
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            // Status dot
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: statusColor.withOpacity(0.12),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(statusIcon, color: statusColor, size: 24),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    visit.customerName,
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 15,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  if (visit.customerAddress != null) ...[
                    const SizedBox(height: 3),
                    Text(
                      visit.customerAddress!,
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.textSecondary),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      _TimeChip(
                        label: visit.checkIn != null
                            ? DateFormat('HH:mm').format(visit.checkIn!)
                            : '--:--',
                        icon: Icons.login_rounded,
                        color: AppColors.success,
                      ),
                      const SizedBox(width: 8),
                      _TimeChip(
                        label: visit.checkOut != null
                            ? DateFormat('HH:mm').format(visit.checkOut!)
                            : '--:--',
                        icon: Icons.logout_rounded,
                        color: AppColors.error,
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: statusColor.withOpacity(0.1),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                visit.statusLabel,
                style: TextStyle(
                    fontSize: 11, color: statusColor, fontWeight: FontWeight.w600),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TimeChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;
  const _TimeChip({required this.label, required this.icon, required this.color});

  @override
  Widget build(BuildContext context) => Row(
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 3),
          Text(label,
              style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600)),
        ],
      );
}

class _EmptyVisits extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.event_available_rounded,
                size: 64, color: AppColors.textSecondary.withOpacity(0.4)),
            const SizedBox(height: 16),
            const Text('Tidak ada kunjungan hari ini',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 16)),
            const SizedBox(height: 8),
            const Text('Selamat beristirahat!',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 13)),
          ],
        ),
      );
}
