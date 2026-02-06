const currentHost = typeof window !== "undefined" ? window.location.hostname : "localhost";
const MANAGER_API = import.meta.env.VITE_MANAGER_API || `http://${currentHost}:8001`;
const APISIX_GATEWAY = import.meta.env.VITE_APISIX_GATEWAY || `http://${currentHost}:9080`;

async function request(path, options = {}) {
  const response = await fetch(`${MANAGER_API}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const message = data?.detail || data || response.statusText;
    throw new Error(message);
  }

  return data;
}

export const api = {
  manager: {
    health: () => request("/health"),
    listModels: () => request("/models"),
    createModel: (payload) => request("/models", { method: "POST", body: JSON.stringify(payload) }),
    deleteModel: (id) => request(`/models/${id}`, { method: "DELETE" }),
    testModelEndpoint: (payload) => request("/models/test", { method: "POST", body: JSON.stringify(payload) }),

    listServers: () => request("/servers"),
    testServer: (payload) => request("/servers/test", { method: "POST", body: JSON.stringify(payload) }),
    createServer: (payload) => request("/servers", { method: "POST", body: JSON.stringify(payload) }),
    deleteServer: (id) => request(`/servers/${id}`, { method: "DELETE" }),

    listUsers: () => request("/users"),
    createUser: (payload) => request("/users", { method: "POST", body: JSON.stringify(payload) }),
    updateUser: (id, payload) => request(`/users/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    deleteUser: (id) => request(`/users/${id}`, { method: "DELETE" }),

    listApiKeys: (mask = false) => request(`/api-keys?mask=${mask ? "true" : "false"}`),
    createApiKey: (payload) => request("/api-keys", { method: "POST", body: JSON.stringify(payload) }),
    updateApiKey: (id, payload) => request(`/api-keys/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    deleteApiKey: (id) => request(`/api-keys/${id}`, { method: "DELETE" }),

    usageStats: (days = 7) => request(`/usage/stats?days=${days}`),
    usageByUser: (days = 7) => request(`/usage/by-user?days=${days}`),
    usageLogs: (limit = 200) => request(`/usage/logs?limit=${limit}`),
    opsStatus: () => request("/ops/status"),
    opsDeploy: () => request("/ops/deploy", { method: "POST" }),
    opsStop: () => request("/ops/stop", { method: "POST" }),
    opsReset: () => request("/ops/reset", { method: "POST" }),
    getEnv: () => request("/ops/env"),
    updateEnv: (values) => request("/ops/env", { method: "PUT", body: JSON.stringify({ values }) })
  },
  gateway: {
    chatCompletion: async (apiKey, payload) => {
      const response = await fetch(`${APISIX_GATEWAY}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`
        },
        body: JSON.stringify(payload)
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || data?.detail || "Gateway request failed");
      }
      return data;
    }
  }
};

export const apiUrls = {
  manager: MANAGER_API,
  gateway: APISIX_GATEWAY
};
