// Routes (PROJECT_SPEC §18.1). A route hidden from a role is also guarded here, but the real
// check is the backend's: this only avoids showing pages that would answer 403.
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth/AuthProvider'
import { SystemStatusProvider } from './auth/SystemStatus'
import AppShell from './components/AppShell'
import { Spinner } from './components/ui'
import { can, landingFor } from './lib/nav'
import Audit from './pages/Audit'
import ChangePassword from './pages/ChangePassword'
import Chat from './pages/Chat'
import Documents from './pages/Documents'
import History from './pages/History'
import Login from './pages/Login'
import Users from './pages/Users'

function RequireSignIn({ children }) {
  const { user, status } = useAuth()
  const location = useLocation()
  if (status === 'loading') {
    return <div className="grid h-full place-items-center text-muted"><Spinner className="h-8 w-8" /></div>
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (user.must_change_password && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }
  return children
}

function Allowed({ any, children }) {
  const { user } = useAuth()
  return any.some((p) => can(user, p)) ? children : <Navigate to={landingFor(user)} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/change-password" element={
        <RequireSignIn><SystemStatusProvider><ChangePassword /></SystemStatusProvider></RequireSignIn>} />
      <Route element={<RequireSignIn><SystemStatusProvider><AppShell /></SystemStatusProvider></RequireSignIn>}>
        <Route index element={<Allowed any={['query:run']}><Chat /></Allowed>} />
        <Route path="history" element={<Allowed any={['history:own']}><History /></Allowed>} />
        <Route path="documents" element={<Allowed any={['docs:read']}><Documents /></Allowed>} />
        <Route path="audit" element={<Allowed any={['audit:read']}><Audit /></Allowed>} />
        <Route path="admin/users" element={<Allowed any={['users:manage']}><Users /></Allowed>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
