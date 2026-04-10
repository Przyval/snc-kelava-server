import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../auth/providers/auth_provider.dart';
import '../dashboard/screens/dashboard_screen.dart';
import '../visits/providers/visit_provider.dart';
import '../visits/screens/visits_screen.dart';
import '../customers/screens/customers_screen.dart';
import '../approvals/screens/approvals_screen.dart';
import '../profile/screens/profile_screen.dart';
import '../scheduling/screens/scheduling_screen.dart';
import '../../core/theme/app_theme.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentIndex = 0;

  void _navigateTo(int index) {
    setState(() => _currentIndex = index);
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthProvider>().user;
    final isSupervisor = user?.isSupervisor ?? false;

    final tabs = _buildTabs(isSupervisor);

    final visitProvider = context.watch<VisitProvider>();
    final isOffline = visitProvider.isOffline;
    final pendingSync = visitProvider.pendingSync;

    return Scaffold(
      body: Column(
        children: [
          // Offline banner
          if (isOffline)
            Material(
              color: Colors.amber.shade700,
              child: SafeArea(
                bottom: false,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                  child: Row(
                    children: [
                      const Icon(Icons.wifi_off_rounded, color: Colors.white, size: 16),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          pendingSync > 0
                              ? 'Offline · $pendingSync aksi menunggu sync'
                              : 'Offline · Menampilkan data terakhir',
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          Expanded(
            child: IndexedStack(
              index: _currentIndex,
              children: tabs.map((t) => t.screen).toList(),
            ),
          ),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (i) => setState(() => _currentIndex = i),
        selectedItemColor: AppColors.primary,
        unselectedItemColor: Colors.grey,
        items: tabs.map((t) {
          final showBadge = t.label == 'Aktivitas' && pendingSync > 0;
          return BottomNavigationBarItem(
            icon: showBadge
                ? Badge(label: Text('$pendingSync'), child: Icon(t.icon))
                : Icon(t.icon),
            label: t.label,
          );
        }).toList(),
      ),
    );
  }

  List<_Tab> _buildTabs(bool isSupervisor) {
    final base = [
      _Tab(
        screen: DashboardScreen(onNavigate: _navigateTo),
        icon: Icons.home_rounded,
        label: 'Beranda',
      ),
      _Tab(
        screen: const VisitsScreen(),
        icon: Icons.calendar_today_rounded,
        label: 'Aktivitas',
      ),
      _Tab(
        screen: const CustomersScreen(),
        icon: Icons.people_outline_rounded,
        label: 'Pelanggan',
      ),
    ];

    // Scheduling tab — koordinator & supervisor see full day view with create
    if (isSupervisor) {
      base.insert(2, _Tab(
        screen: const SchedulingScreen(),
        icon: Icons.event_note_rounded,
        label: 'Jadwal',
      ));
      base.add(_Tab(
        screen: const ApprovalsScreen(),
        icon: Icons.pending_actions_rounded,
        label: 'Approval',
      ));
    }

    base.add(_Tab(
      screen: const ProfileScreen(),
      icon: Icons.person_outline_rounded,
      label: 'Profil',
    ));

    return base;
  }
}

class _Tab {
  final Widget screen;
  final IconData icon;
  final String label;
  const _Tab({required this.screen, required this.icon, required this.label});
}
