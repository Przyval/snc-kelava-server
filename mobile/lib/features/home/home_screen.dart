import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../auth/providers/auth_provider.dart';
import '../dashboard/screens/dashboard_screen.dart';
import '../visits/screens/visits_screen.dart';
import '../customers/screens/customers_screen.dart';
import '../approvals/screens/approvals_screen.dart';
import '../profile/screens/profile_screen.dart';

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

    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: tabs.map((t) => t.screen).toList(),
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (i) => setState(() => _currentIndex = i),
        items: tabs
            .map((t) => BottomNavigationBarItem(icon: Icon(t.icon), label: t.label))
            .toList(),
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

    if (isSupervisor) {
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
