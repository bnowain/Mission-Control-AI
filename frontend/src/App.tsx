import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout/Layout'
import DashboardPage from './pages/DashboardPage'

// Lazy imports for remaining pages (filled in step by step)
import TasksPage from './pages/TasksPage'
import TaskDetailPage from './pages/TaskDetailPage'
import PlansPage from './pages/PlansPage'
import PlanDetailPage from './pages/PlanDetailPage'
import CodexPage from './pages/CodexPage'
import RouterPage from './pages/RouterPage'
import TelemetryPage from './pages/TelemetryPage'
import ReportsPage from './pages/ReportsPage'
import SqlConsolePage from './pages/SqlConsolePage'
import WorkersPage from './pages/WorkersPage'
import ArtifactsPage from './pages/ArtifactsPage'
import IntegrationsPage from './pages/IntegrationsPage'
import ValidationPage from './pages/ValidationPage'
import SettingsPage from './pages/SettingsPage'
import PlannerPage from './pages/PlannerPage'
import CoderPage from './pages/CoderPage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/tasks/:id" element={<TaskDetailPage />} />
        <Route path="/plans" element={<PlansPage />} />
        <Route path="/plans/:id" element={<PlanDetailPage />} />
        <Route path="/codex" element={<CodexPage />} />
        <Route path="/router" element={<RouterPage />} />
        <Route path="/telemetry" element={<TelemetryPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/sql" element={<SqlConsolePage />} />
        <Route path="/workers" element={<WorkersPage />} />
        <Route path="/artifacts" element={<ArtifactsPage />} />
        <Route path="/integrations" element={<IntegrationsPage />} />
        <Route path="/validation" element={<ValidationPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/planner" element={<PlannerPage />} />
        <Route path="/coder" element={<CoderPage />} />
      </Routes>
    </Layout>
  )
}
