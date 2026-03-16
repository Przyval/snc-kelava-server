import { useEffect, useState } from 'react';
import { Card, Grid, Title, Text, Metric, TabGroup, TabList, Tab, TabPanels, TabPanel, DonutChart, AreaChart, Badge } from '@tremor/react';
import { fetchStats, fetchLeaderboard, fetchWatchlist, fetchTrends } from './services/dataService';
import type { DashboardStats, TechnicianLeaderboard, WatchlistItem, TrendItem } from './services/dataService';

function App() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [leaderboard, setLeaderboard] = useState<TechnicianLeaderboard[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [trends, setTrends] = useState<TrendItem[]>([]);

  useEffect(() => {
    fetchStats().then(setStats);
    fetchLeaderboard().then(setLeaderboard);
    fetchWatchlist().then(setWatchlist);
    fetchTrends().then(setTrends);
  }, []);

  if (!stats) return <div className="p-10">Loading Dashboard...</div>;

  return (
    <main className="p-12 bg-gray-50 min-h-screen">
      <div className="mb-6">
        <Title className="text-3xl">SanoCare Command Center</Title>
        <Text>Operational Intelligence & KPI Dashboard</Text>
        <Text className="text-xs text-gray-400 mt-1">Generated: {new Date(stats.generated_at).toLocaleString()}</Text>
      </div>

      <TabGroup className="mt-6">
        <TabList>
          <Tab>Executive View</Tab>
          <Tab>Ops Control Room</Tab>
          <Tab>HR & Leaderboard</Tab>
        </TabList>
        <TabPanels>

          {/* Executive View */}
          <TabPanel>
            <Grid numItems={1} numItemsSm={2} numItemsLg={4} className="gap-6 mt-6">
              <Card decoration="top" decorationColor="blue">
                <Text>Operational Health Score</Text>
                <Metric>{stats.health_score}/100</Metric>
              </Card>
              <Card decoration="top" decorationColor="emerald">
                <Text>Coverage Ratio</Text>
                <Metric>{stats.coverage_ratio}%</Metric>
              </Card>
              <Card decoration="top" decorationColor="amber">
                <Text>On-Time Rate</Text>
                <Metric>{stats.on_time_rate}%</Metric>
              </Card>
              <Card decoration="top" decorationColor="rose">
                <Text>Photo Compliance</Text>
                <Metric>{stats.photo_compliance}%</Metric>
              </Card>
            </Grid>

            <div className="mt-6">
              <Card>
                <Title>Visit Trends (Last 30 Days)</Title>
                <AreaChart
                  className="h-72 mt-4"
                  data={trends.slice(-30)}
                  index="date"
                  categories={["planned", "completed", "on_time"]}
                  colors={["indigo", "emerald", "amber"]}
                />
              </Card>
            </div>
          </TabPanel>

          {/* Ops Control Room */}
          <TabPanel>
            <Grid numItems={1} numItemsLg={2} className="gap-6 mt-6">
              <Card>
                <Title>Critical Watchlist</Title>
                <Text>Technicians requiring immediate attention</Text>
                <div className="mt-4 h-96 overflow-y-auto">
                  <table className="w-full text-left">
                    <thead className="bg-gray-100 text-gray-500 text-sm">
                      <tr>
                        <th className="p-2">Technician</th>
                        <th className="p-2">Issue</th>
                        <th className="p-2">Count</th>
                        <th className="p-2">Priority</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y text-sm">
                      {watchlist.map((item, idx) => (
                        <tr key={idx}>
                          <td className="p-2 font-medium">{item.technician} <span className="text-xs text-gray-400">({item.segment})</span></td>
                          <td className="p-2 text-red-600 font-bold">{item.issue}</td>
                          <td className="p-2">{item.count}</td>
                          <td className="p-2"><Badge color={item.priority === 'HIGH' ? 'red' : 'yellow'}>{item.priority}</Badge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card>
                <Title>Compliance Issues by Segment</Title>
                <DonutChart
                  className="mt-6"
                  data={watchlist}
                  category="count"
                  index="segment"
                  colors={["slate", "violet", "indigo", "rose", "cyan", "amber"]}
                  variant="pie"
                />
              </Card>
            </Grid>
          </TabPanel>

          {/* HR & Leaderboard */}
          <TabPanel>
            <Card className="mt-6">
              <Title>Technician Leaderboard</Title>
              <Text>Performance ranking based on FAIR scoring</Text>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-gray-100 font-semibold text-gray-600">
                    <tr>
                      <th className="p-3">Rank</th>
                      <th className="p-3">Name</th>
                      <th className="p-3">Segment</th>
                      <th className="p-3">Grade</th>
                      <th className="p-3">Score</th>
                      <th className="p-3">Compl.</th>
                      <th className="p-3">On-Time</th>
                      <th className="p-3">Photo</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {leaderboard.map((tech) => (
                      <tr key={tech.id} className="hover:bg-gray-50">
                        <td className="p-3 font-bold text-gray-500">#{tech.rank}</td>
                        <td className="p-3 font-medium text-gray-900">{tech.name}</td>
                        <td className="p-3 text-gray-500">{tech.segment}</td>
                        <td className="p-3">
                          <Badge color={
                            tech.grade === 'A' ? 'emerald' :
                              tech.grade === 'B' ? 'blue' :
                                tech.grade === 'C' ? 'yellow' : 'red'
                          }>{tech.grade}</Badge>
                        </td>
                        <td className="p-3 font-bold">{tech.score}</td>
                        <td className="p-3">{tech.metrics.completion}%</td>
                        <td className="p-3">{tech.metrics.on_time}%</td>
                        <td className="p-3">{tech.metrics.photo_compliance}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </TabPanel>

        </TabPanels>
      </TabGroup>
    </main>
  );
}

export default App;
