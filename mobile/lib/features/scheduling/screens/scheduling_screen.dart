import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../providers/scheduling_provider.dart';
import '../../../core/models/road_plan_model.dart';
import '../../../core/theme/app_theme.dart';
import '../../../features/auth/providers/auth_provider.dart';
import 'create_road_plan_screen.dart';

class SchedulingScreen extends StatefulWidget {
  const SchedulingScreen({super.key});

  @override
  State<SchedulingScreen> createState() => _SchedulingScreenState();
}

class _SchedulingScreenState extends State<SchedulingScreen> {
  DateTime _selectedDate = DateTime.now();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final dateStr = DateFormat('yyyy-MM-dd').format(_selectedDate);
    await context.read<SchedulingProvider>().loadForDate(dateStr);
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _selectedDate,
      firstDate: DateTime.now().subtract(const Duration(days: 30)),
      lastDate: DateTime.now().add(const Duration(days: 90)),
      locale: const Locale('id'),
    );
    if (picked != null && mounted) {
      setState(() => _selectedDate = picked);
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthProvider>().user;
    final sched = context.watch<SchedulingProvider>();
    final isKoordinator = user?.isKoordinator ?? false;
    final fmt = DateFormat('EEEE, d MMMM yyyy', 'id');

    return Scaffold(
      backgroundColor: AppColors.background,
      body: CustomScrollView(
        slivers: [
          // Header
          SliverAppBar(
            expandedHeight: 120,
            pinned: true,
            flexibleSpace: FlexibleSpaceBar(
              background: Container(
                decoration: const BoxDecoration(
                  gradient: LinearGradient(
                    colors: [AppColors.primary, AppColors.primaryDark],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                ),
                child: SafeArea(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Jadwal Kunjungan',
                            style: TextStyle(
                                color: Colors.white,
                                fontSize: 22,
                                fontWeight: FontWeight.w700)),
                        const SizedBox(height: 4),
                        GestureDetector(
                          onTap: _pickDate,
                          child: Row(
                            children: [
                              Text(fmt.format(_selectedDate),
                                  style: const TextStyle(
                                      color: Colors.white70, fontSize: 13)),
                              const SizedBox(width: 4),
                              const Icon(Icons.calendar_today,
                                  color: Colors.white70, size: 14),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
            actions: [
              // Date navigation
              IconButton(
                icon: const Icon(Icons.chevron_left, color: Colors.white),
                onPressed: () {
                  setState(() => _selectedDate =
                      _selectedDate.subtract(const Duration(days: 1)));
                  _load();
                },
              ),
              IconButton(
                icon: const Icon(Icons.chevron_right, color: Colors.white),
                onPressed: () {
                  setState(() =>
                      _selectedDate = _selectedDate.add(const Duration(days: 1)));
                  _load();
                },
              ),
            ],
          ),

          // Summary row
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Row(
                children: [
                  _SummaryChip(
                    label: 'Total',
                    count: sched.plans.length,
                    color: AppColors.primary,
                  ),
                  const SizedBox(width: 8),
                  _SummaryChip(
                    label: 'Selesai',
                    count: sched.plans.where((p) => p.isCompleted).length,
                    color: Colors.green,
                  ),
                  const SizedBox(width: 8),
                  _SummaryChip(
                    label: 'Berlangsung',
                    count: sched.plans.where((p) => p.isInProgress).length,
                    color: Colors.blue,
                  ),
                  const SizedBox(width: 8),
                  _SummaryChip(
                    label: 'Baru',
                    count: sched.plans.where((p) => p.isNew).length,
                    color: Colors.orange,
                  ),
                ],
              ),
            ),
          ),

          // List
          if (sched.loading)
            const SliverFillRemaining(
              child: Center(child: CircularProgressIndicator()),
            )
          else if (sched.plans.isEmpty)
            SliverFillRemaining(
              child: Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.event_busy_rounded,
                        size: 64, color: Colors.grey.shade300),
                    const SizedBox(height: 12),
                    Text('Tidak ada jadwal hari ini',
                        style: TextStyle(
                            color: Colors.grey.shade500, fontSize: 15)),
                    if (isKoordinator) ...[
                      const SizedBox(height: 16),
                      ElevatedButton.icon(
                        onPressed: _goCreateRoadPlan,
                        icon: const Icon(Icons.add),
                        label: const Text('Buat Jadwal'),
                      ),
                    ],
                  ],
                ),
              ),
            )
          else
            SliverPadding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              sliver: SliverList(
                delegate: SliverChildBuilderDelegate(
                  (context, i) {
                    final plan = sched.plans[i];
                    return _RoadPlanCard(
                      plan: plan,
                      isKoordinator: isKoordinator,
                      onCancel: isKoordinator && plan.source == 'snc'
                          ? () => _confirmCancel(plan)
                          : null,
                    );
                  },
                  childCount: sched.plans.length,
                ),
              ),
            ),
        ],
      ),
      floatingActionButton: isKoordinator
          ? FloatingActionButton.extended(
              onPressed: _goCreateRoadPlan,
              backgroundColor: AppColors.primary,
              icon: const Icon(Icons.add),
              label: const Text('Buat Jadwal'),
            )
          : null,
    );
  }

  Future<void> _goCreateRoadPlan() async {
    final created = await Navigator.push<bool>(
      context,
      MaterialPageRoute(
          builder: (_) => const CreateRoadPlanScreen()),
    );
    if (created == true) _load();
  }

  Future<void> _confirmCancel(RoadPlanModel plan) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Batalkan Jadwal?'),
        content: Text('Jadwal ke ${plan.customerName} akan dibatalkan.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Tidak')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Batalkan'),
          ),
        ],
      ),
    );
    if (ok == true && mounted) {
      await context.read<SchedulingProvider>().cancelRoadPlan(plan.id);
      _load();
    }
  }
}

// ── Widgets ──────────────────────────────────────────────

class _SummaryChip extends StatelessWidget {
  final String label;
  final int count;
  final Color color;
  const _SummaryChip(
      {required this.label, required this.count, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('$count',
              style: TextStyle(
                  fontWeight: FontWeight.w700, color: color, fontSize: 14)),
          const SizedBox(width: 4),
          Text(label,
              style: TextStyle(color: color.withOpacity(0.8), fontSize: 12)),
        ],
      ),
    );
  }
}

class _RoadPlanCard extends StatelessWidget {
  final RoadPlanModel plan;
  final bool isKoordinator;
  final VoidCallback? onCancel;

  const _RoadPlanCard({
    required this.plan,
    required this.isKoordinator,
    this.onCancel,
  });

  Color get _statusColor => switch (plan.status) {
        'Selesai' => Colors.green,
        'Berjalan' => Colors.blue,
        'Baru' => Colors.orange,
        'Cancelled' => Colors.grey,
        _ => Colors.grey,
      };

  @override
  Widget build(BuildContext context) {
    final timeFmt = DateFormat('HH:mm', 'id');

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.grey.shade200),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Status indicator
            Container(
              width: 4,
              height: 60,
              decoration: BoxDecoration(
                color: _statusColor,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(plan.customerName,
                            style: const TextStyle(
                                fontWeight: FontWeight.w700, fontSize: 14)),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: _statusColor.withOpacity(0.1),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(plan.statusLabel,
                            style: TextStyle(
                                color: _statusColor,
                                fontSize: 11,
                                fontWeight: FontWeight.w600)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(plan.technicianName,
                      style: TextStyle(
                          color: Colors.grey.shade600, fontSize: 12)),
                  if (plan.customerAddress != null)
                    Text(plan.customerAddress!,
                        style: TextStyle(
                            color: Colors.grey.shade500, fontSize: 11),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      Icon(Icons.access_time,
                          size: 12, color: Colors.grey.shade500),
                      const SizedBox(width: 3),
                      Text(timeFmt.format(plan.visitDate),
                          style: TextStyle(
                              color: Colors.grey.shade500, fontSize: 11)),
                      if (plan.kontrakNo != null) ...[
                        const SizedBox(width: 10),
                        Icon(Icons.description_outlined,
                            size: 12, color: Colors.grey.shade500),
                        const SizedBox(width: 3),
                        Text(plan.kontrakNo!,
                            style: TextStyle(
                                color: Colors.grey.shade500, fontSize: 11)),
                      ],
                      const Spacer(),
                      // Source badge
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                          color: plan.source == 'snc'
                              ? AppColors.primary.withOpacity(0.1)
                              : Colors.grey.shade100,
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          plan.source == 'snc' ? 'SNC' : 'Kelava',
                          style: TextStyle(
                            fontSize: 9,
                            fontWeight: FontWeight.w700,
                            color: plan.source == 'snc'
                                ? AppColors.primary
                                : Colors.grey.shade500,
                          ),
                        ),
                      ),
                      if (onCancel != null) ...[
                        const SizedBox(width: 8),
                        GestureDetector(
                          onTap: onCancel,
                          child: Icon(Icons.cancel_outlined,
                              size: 18, color: Colors.red.shade400),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
