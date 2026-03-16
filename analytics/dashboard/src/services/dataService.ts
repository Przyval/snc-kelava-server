export interface DashboardStats {
    generated_at: string;
    health_score: number;
    total_visits: number;
    coverage_ratio: number;
    on_time_rate: number;
    photo_compliance: number;
    active_technicians: number;
}

export interface TechnicianLeaderboard {
    rank: number;
    id: number;
    name: string;
    segment: string;
    score: number;
    grade: string;
    metrics: {
        completion: number;
        on_time: number;
        duration_compliance: number;
        photo_compliance: number;
        productivity_avg: number;
    };
}

export interface WatchlistItem {
    technician: string;
    segment: string;
    issue: string;
    count: number;
    priority: "HIGH" | "MEDIUM" | "LOW";
}

export interface TrendItem {
    date: string;
    planned: number;
    completed: number;
    on_time: number;
}

const DATA_BASE_URL = '/data';

export const fetchStats = async (): Promise<DashboardStats> => {
    const res = await fetch(`${DATA_BASE_URL}/dashboard_stats.json`);
    return res.json();
};

export const fetchLeaderboard = async (): Promise<TechnicianLeaderboard[]> => {
    const res = await fetch(`${DATA_BASE_URL}/leaderboard_full.json`);
    return res.json();
};

export const fetchWatchlist = async (): Promise<WatchlistItem[]> => {
    const res = await fetch(`${DATA_BASE_URL}/watchlist.json`);
    return res.json();
};

export const fetchTrends = async (): Promise<TrendItem[]> => {
    const res = await fetch(`${DATA_BASE_URL}/trends.json`);
    return res.json();
};
