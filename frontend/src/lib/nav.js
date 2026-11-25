/**
 * Menus by permission (design brief §3; PROJECT_SPEC §18.1). Hiding a menu is a convenience
 * only: the backend checks every request (SEC-02).
 */

export const NAV = [
  { to: '/', label: 'Chat', icon: 'chat', any: ['query:run'] },
  { to: '/history', label: 'History', icon: 'history', any: ['history:own'] },
  { to: '/documents', label: 'Documents', icon: 'documents', any: ['docs:read'] },
  { to: '/audit', label: 'Audit', icon: 'shield', any: ['audit:read'] },
  { to: '/admin/users', label: 'Users', icon: 'users', any: ['users:manage'] },
]

export const can = (user, permission) => Boolean(user?.permissions?.includes(permission))

export function navFor(user) {
  return NAV.filter((item) => item.any.some((p) => can(user, p)))
}

/** The auditor cannot ask questions, so lands on the audit trail; everyone else on Chat. */
export function landingFor(user) {
  if (can(user, 'query:run')) return '/'
  if (can(user, 'audit:read')) return '/audit'
  return '/documents'
}

export const ROLE_LABEL = { viewer: 'Viewer', qa_user: 'QA user', auditor: 'Auditor',
  admin: 'Admin' }

export const ROLE_DESCRIPTION = {
  viewer: 'Asks questions and sees their own history.',
  qa_user: 'Like a viewer; will manage documents (Tier 2).',
  auditor: 'Reviews and exports the audit trail. Cannot ask questions.',
  admin: 'Everything, plus users and system health.',
}
