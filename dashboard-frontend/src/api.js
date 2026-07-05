const jsonHeaders = { "Content-Type": "application/json" };

async function request(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: jsonHeaders,
    ...options,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  let data = {};
  try {
    data = await res.json();
  } catch {
    // no body
  }
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

export const api = {
  me: () => request("/api/me"),
  logout: () => request("/api/logout", { method: "POST" }),
  guilds: () => request("/api/guilds"),
  commands: () => request("/api/commands"),
  guildDetail: (id) => request(`/api/guilds/${id}`),
  updateSettings: (id, payload) => request(`/api/guilds/${id}/settings`, { method: "POST", body: payload }),
  clearWarning: (id, userId) => request(`/api/guilds/${id}/warnings/${userId}/clear`, { method: "POST" }),
  addAutorole: (id, role_id) => request(`/api/guilds/${id}/autoroles`, { method: "POST", body: { role_id } }),
  removeAutorole: (id, roleId) => request(`/api/guilds/${id}/autoroles/${roleId}`, { method: "DELETE" }),
  createReactionRole: (id, payload) => request(`/api/guilds/${id}/reactionroles`, { method: "POST", body: payload }),
  removeReactionRole: (id, mappingId) =>
    request(`/api/guilds/${id}/reactionroles/${mappingId}`, { method: "DELETE" }),
  removeReactionRoleMessage: (id, messageId) =>
    request(`/api/guilds/${id}/reactionroles/message/${messageId}`, { method: "DELETE" }),
  roles: (id) => request(`/api/guilds/${id}/roles`),
  channels: (id) => request(`/api/guilds/${id}/channels`),
  members: (id, q = "") => request(`/api/guilds/${id}/members${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  kickMember: (id, userId, reason) =>
    request(`/api/guilds/${id}/members/${userId}/kick`, { method: "POST", body: { reason } }),
  banMember: (id, userId, reason) =>
    request(`/api/guilds/${id}/members/${userId}/ban`, { method: "POST", body: { reason } }),
  timeoutMember: (id, userId, reason, duration_seconds) =>
    request(`/api/guilds/${id}/members/${userId}/timeout`, { method: "POST", body: { reason, duration_seconds } }),
  untimeoutMember: (id, userId, reason) =>
    request(`/api/guilds/${id}/members/${userId}/untimeout`, { method: "POST", body: { reason } }),
  warnMember: (id, userId, reason) =>
    request(`/api/guilds/${id}/members/${userId}/warn`, { method: "POST", body: { reason } }),
  listMemberNotes: (id, userId) => request(`/api/guilds/${id}/members/${userId}/notes`),
  addMemberNote: (id, userId, note) =>
    request(`/api/guilds/${id}/members/${userId}/notes`, { method: "POST", body: { note } }),
  removeMemberNote: (id, userId, noteId) =>
    request(`/api/guilds/${id}/members/${userId}/notes/${noteId}`, { method: "DELETE" }),
  addTag: (id, name, content) => request(`/api/guilds/${id}/tags`, { method: "POST", body: { name, content } }),
  removeTag: (id, name) => request(`/api/guilds/${id}/tags/${encodeURIComponent(name)}`, { method: "DELETE" }),
  stats: (id, days = 14) => request(`/api/guilds/${id}/stats?days=${days}`),
  levels: (id) => request(`/api/guilds/${id}/levels`),
  resetUserXp: (id, userId) => request(`/api/guilds/${id}/levels/${userId}/reset`, { method: "POST" }),
  adjustUserXp: (id, userId, amount) =>
    request(`/api/guilds/${id}/levels/${userId}/adjust`, { method: "POST", body: { amount } }),
  addLevelRole: (id, level, role_id) =>
    request(`/api/guilds/${id}/level-roles`, { method: "POST", body: { level, role_id } }),
  removeLevelRole: (id, level) => request(`/api/guilds/${id}/level-roles/${level}`, { method: "DELETE" }),
  announce: (id, payload) => request(`/api/guilds/${id}/announce`, { method: "POST", body: payload }),
  dangerClearAllWarnings: (id) => request(`/api/guilds/${id}/danger/clear-all-warnings`, { method: "POST" }),
  dangerResetAllXp: (id) => request(`/api/guilds/${id}/danger/reset-all-xp`, { method: "POST" }),
  dangerWipeReactionRoles: (id) => request(`/api/guilds/${id}/danger/wipe-reaction-roles`, { method: "POST" }),
};
