import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';

/// Offline cache — stores visits and dashboard data in local SQLite.
/// Used when device has no internet connection.
class OfflineCacheService {
  static final OfflineCacheService instance = OfflineCacheService._();
  OfflineCacheService._();

  Database? _db;

  Future<Database> get db async {
    _db ??= await _initDb();
    return _db!;
  }

  Future<Database> _initDb() async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, 'snc_cache.db');

    return openDatabase(
      path,
      version: 1,
      onCreate: (db, version) async {
        // Cached visits (today's schedule)
        await db.execute('''
          CREATE TABLE IF NOT EXISTS cached_visits (
            id INTEGER PRIMARY KEY,
            road_plan_id INTEGER,
            customer_name TEXT NOT NULL,
            customer_address TEXT,
            kontrak_no TEXT,
            status TEXT NOT NULL,
            scheduled_date TEXT,
            check_in TEXT,
            check_out TEXT,
            latitude REAL,
            longitude REAL,
            remarks TEXT,
            visit_type TEXT,
            cached_at TEXT NOT NULL
          )
        ''');

        // Cached dashboard stats
        await db.execute('''
          CREATE TABLE IF NOT EXISTS cached_dashboard (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            cached_at TEXT NOT NULL
          )
        ''');

        // Pending actions (check-in/check-out queued while offline)
        await db.execute('''
          CREATE TABLE IF NOT EXISTS pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            visit_id INTEGER NOT NULL,
            latitude REAL,
            longitude REAL,
            remarks TEXT,
            created_at TEXT NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0
          )
        ''');
      },
    );
  }

  // ── Visits ──────────────────────────────────────────────

  /// Cache today's visit list
  Future<void> cacheVisits(List<Map<String, dynamic>> visits) async {
    final database = await db;
    final now = DateTime.now().toIso8601String();

    await database.transaction((txn) async {
      await txn.delete('cached_visits');
      for (final v in visits) {
        await txn.insert('cached_visits', {
          'id': v['id'],
          'road_plan_id': v['road_plan_id'],
          'customer_name': v['customer_name'] ?? '-',
          'customer_address': v['customer_address'],
          'kontrak_no': v['kontrak_no'],
          'status': v['status'] ?? 'SCHEDULED',
          'scheduled_date': v['scheduled_date'],
          'check_in': v['check_in'],
          'check_out': v['check_out'],
          'latitude': v['latitude'],
          'longitude': v['longitude'],
          'remarks': v['remarks'],
          'visit_type': v['visit_type'],
          'cached_at': now,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
    });
  }

  /// Get cached visits
  Future<List<Map<String, dynamic>>> getCachedVisits() async {
    final database = await db;
    return database.query('cached_visits', orderBy: 'scheduled_date ASC');
  }

  /// Update a single visit's check_in/check_out locally (optimistic update)
  Future<void> updateVisitLocally(int visitId, {
    String? checkIn,
    String? checkOut,
    String? status,
  }) async {
    final database = await db;
    final data = <String, dynamic>{};
    if (checkIn != null) data['check_in'] = checkIn;
    if (checkOut != null) data['check_out'] = checkOut;
    if (status != null) data['status'] = status;
    if (data.isEmpty) return;

    await database.update(
      'cached_visits',
      data,
      where: 'id = ?',
      whereArgs: [visitId],
    );
  }

  // ── Dashboard ────────────────────────────────────────────

  /// Cache dashboard stats as key-value JSON
  Future<void> cacheDashboard(Map<String, dynamic> stats) async {
    final database = await db;
    final now = DateTime.now().toIso8601String();

    await database.transaction((txn) async {
      await txn.delete('cached_dashboard');
      for (final entry in stats.entries) {
        await txn.insert('cached_dashboard', {
          'key': entry.key,
          'value': jsonEncode(entry.value),
          'cached_at': now,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
    });
  }

  /// Get cached dashboard stats
  Future<Map<String, dynamic>?> getCachedDashboard() async {
    final database = await db;
    final rows = await database.query('cached_dashboard');
    if (rows.isEmpty) return null;

    final result = <String, dynamic>{};
    for (final row in rows) {
      try {
        result[row['key'] as String] = jsonDecode(row['value'] as String);
      } catch (_) {
        result[row['key'] as String] = row['value'];
      }
    }
    return result;
  }

  /// Returns true if cached data is fresh (within maxAge)
  Future<bool> isCacheFresh({Duration maxAge = const Duration(hours: 1)}) async {
    final database = await db;
    final rows = await database.query(
      'cached_visits',
      columns: ['cached_at'],
      limit: 1,
    );
    if (rows.isEmpty) return false;

    final cachedAt = DateTime.tryParse(rows.first['cached_at'] as String);
    if (cachedAt == null) return false;
    return DateTime.now().difference(cachedAt) < maxAge;
  }

  // ── Pending Actions ──────────────────────────────────────

  /// Queue a check-in or check-out action to be synced later
  Future<void> queueAction({
    required String actionType, // 'checkin' | 'checkout'
    required int visitId,
    double? latitude,
    double? longitude,
    String? remarks,
  }) async {
    final database = await db;
    await database.insert('pending_actions', {
      'action_type': actionType,
      'visit_id': visitId,
      'latitude': latitude,
      'longitude': longitude,
      'remarks': remarks,
      'created_at': DateTime.now().toIso8601String(),
      'retry_count': 0,
    });
  }

  /// Get all pending actions (oldest first)
  Future<List<Map<String, dynamic>>> getPendingActions() async {
    final database = await db;
    return database.query(
      'pending_actions',
      orderBy: 'created_at ASC',
    );
  }

  /// Delete a pending action after successful sync
  Future<void> deletePendingAction(int id) async {
    final database = await db;
    await database.delete('pending_actions', where: 'id = ?', whereArgs: [id]);
  }

  /// Increment retry count for a pending action
  Future<void> incrementRetry(int id) async {
    final database = await db;
    await database.rawUpdate(
      'UPDATE pending_actions SET retry_count = retry_count + 1 WHERE id = ?',
      [id],
    );
  }

  Future<int> pendingCount() async {
    final database = await db;
    final result = await database.rawQuery('SELECT COUNT(*) as c FROM pending_actions');
    return (result.first['c'] as int?) ?? 0;
  }

  // ── Cleanup ──────────────────────────────────────────────

  Future<void> clearAll() async {
    final database = await db;
    await database.delete('cached_visits');
    await database.delete('cached_dashboard');
  }
}
