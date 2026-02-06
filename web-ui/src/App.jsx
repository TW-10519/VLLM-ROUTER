import React, { useEffect, useMemo, useState } from "react";
import { api, apiUrls } from "./api.js";

const defaultNewModel = {
  name: "",
  backend_host: "dgx-01",
  backend_port: 8000,
  description: ""
};

const defaultNewServer = {
  hostname: "",
  port: 8000,
  description: ""
};

const defaultNewUser = {
  username: "",
  email: ""
};

export default function App() {
  const [managerOnline, setManagerOnline] = useState(false);
  const [models, setModels] = useState([]);
  const [servers, setServers] = useState([]);
  const [users, setUsers] = useState([]);
  const [keys, setKeys] = useState([]);
  const [usageLogs, setUsageLogs] = useState([]);
  const [testState, setTestState] = useState({ apiKey: "", model: "", message: "Hello from vLLM Platform" });
  const [testResponse, setTestResponse] = useState(null);
  const [opsStatus, setOpsStatus] = useState(null);
  const [envValues, setEnvValues] = useState({});
  const [activeTab, setActiveTab] = useState("dashboard");
  const [notice, setNotice] = useState(null);

  // Dialog states
  const [showAddModel, setShowAddModel] = useState(false);
  const [showAddServer, setShowAddServer] = useState(false);
  const [showAddUser, setShowAddUser] = useState(false);
  const [showAddKey, setShowAddKey] = useState(false);

  const [newModel, setNewModel] = useState(defaultNewModel);
  const [newServer, setNewServer] = useState(defaultNewServer);
  const [newUser, setNewUser] = useState(defaultNewUser);
  const [newKeyName, setNewKeyName] = useState("");
  const [selectedUserForKey, setSelectedUserForKey] = useState("");
  const [modelTestResult, setModelTestResult] = useState(null);

  const loadData = async () => {
    try {
      await api.manager.health();
      setManagerOnline(true);
      const [modelData, serverData, userData, keyData] = await Promise.all([
        api.manager.listModels(),
        api.manager.listServers(),
        api.manager.listUsers(),
        api.manager.listApiKeys(false)
      ]);
      setModels(modelData);
      setServers(serverData);
      setUsers(userData);
      setKeys(keyData);
      
      // Load usage logs
      const usage = await api.manager.usageLogs(200);
      setUsageLogs(usage?.logs || []);
    } catch (error) {
      setManagerOnline(false);
      setNotice({ type: "error", message: error.message });
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreateModel = async (event) => {
    event.preventDefault();
    try {
      await api.manager.createModel({ ...newModel, backend_port: Number(newModel.backend_port) });
      setNewModel(defaultNewModel);
      setModelTestResult(null);
      setShowAddModel(false);
      await loadData();
      setNotice({ type: "success", message: "Model registered" });
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleTestModel = async () => {
    setModelTestResult(null);
    try {
      const result = await api.manager.testModelEndpoint({
        backend_host: newModel.backend_host,
        backend_port: Number(newModel.backend_port)
      });
      setModelTestResult(result);
      if (result.ok) {
        setNotice({ type: "success", message: "vLLM endpoint reachable" });
      } else {
        setNotice({ type: "error", message: result.error || "Endpoint test failed" });
      }
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleCreateServer = async (event) => {
    event.preventDefault();
    try {
      const testResult = await api.manager.testServer({
        hostname: newServer.hostname,
        port: Number(newServer.port)
      });
      if (!testResult.ok) {
        setNotice({ type: "error", message: testResult.error || "Server unreachable" });
        return;
      }
      await api.manager.createServer({
        hostname: newServer.hostname,
        port: Number(newServer.port),
        description: newServer.description
      });
      setNewServer(defaultNewServer);
      setShowAddServer(false);
      await loadData();
      setNotice({ type: "success", message: "Server registered" });
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleCreateUser = async (event) => {
    event.preventDefault();
    try {
      await api.manager.createUser({
        username: newUser.username,
        email: newUser.email
      });
      setNewUser(defaultNewUser);
      setShowAddUser(false);
      await loadData();
      setNotice({ type: "success", message: "User created" });
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleCreateKey = async (event) => {
    event.preventDefault();
    try {
      const payload = {
        user_id: Number(selectedUserForKey),
        name: newKeyName
      };
      const data = await api.manager.createApiKey(payload);
      setNotice({ type: "success", message: `API key created: ${data.key}` });
      setNewKeyName("");
      setSelectedUserForKey("");
      setShowAddKey(false);
      await loadData();
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleDeleteModel = async (id) => {
    if (!confirm("Delete this model?")) return;
    try {
      await api.manager.deleteModel(id);
      await loadData();
      setNotice({ type: "success", message: "Model deleted" });
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleDeleteServer = async (id) => {
    if (!confirm("Delete this server?")) return;
    try {
      await api.manager.deleteServer(id);
      await loadData();
      setNotice({ type: "success", message: "Server deleted" });
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleDeleteUser = async (id) => {
    if (!confirm("Delete this user? This also deletes all API keys.")) return;
    try {
      await api.manager.deleteUser(id);
      await loadData();
      setNotice({ type: "success", message: "User deleted" });
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleDeleteKey = async (id) => {
    if (!confirm("Delete this API key?")) return;
    try {
      await api.manager.deleteApiKey(id);
      await loadData();
      setNotice({ type: "success", message: "API key deleted" });
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const handleGatewayTest = async () => {
    setTestResponse(null);
    try {
      const payload = {
        model: testState.model,
        messages: [{ role: "user", content: testState.message }],
        max_tokens: 64
      };
      const data = await api.gateway.chatCompletion(testState.apiKey, payload);
      setTestResponse(data);
    } catch (error) {
      setNotice({ type: "error", message: error.message });
    }
  };

  const maskKey = (key) => `${key.slice(0, 12)}...`;

  const tabs = useMemo(() => [
    { id: "dashboard", label: "Dashboard" },
    { id: "servers", label: "Servers" },
    { id: "models", label: "Models" },
    { id: "users", label: "Users & Keys" },
    { id: "usage", label: "Usage" },
    { id: "test", label: "Test Gateway" },
    { id: "ops", label: "Gateway Ops" }
  ], []);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-icon">⚡</span>
          <div>
            <h1>vLLM Platform</h1>
            <p>Multi-DGX Gateway Manager</p>
          </div>
        </div>
        <div className={`status ${managerOnline ? "online" : "offline"}`}>
          {managerOnline ? "Manager Online" : "Manager Offline"}
        </div>
        <nav>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={activeTab === tab.id ? "active" : ""}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <small>Manager API: {apiUrls.manager}</small>
          <small>Gateway: {apiUrls.gateway}</small>
        </div>
      </aside>

      <main className="content">
        <header className="content-header">
          <div>
            <h2>{tabs.find((tab) => tab.id === activeTab)?.label}</h2>
          </div>
          <button className="secondary" onClick={loadData}>Refresh</button>
        </header>

        {notice && (
          <div className={`notice ${notice.type}`}>
            <span>{notice.message}</span>
            <button onClick={() => setNotice(null)}>×</button>
          </div>
        )}

        {activeTab === "dashboard" && (
          <section className="panel">
            <h3>Platform Status</h3>
            <div className="stats-grid">
              <div className="stat-card">
                <span className="stat-label">Models</span>
                <span className="stat-value">{models.length}</span>
              </div>
              <div className="stat-card">
                <span className="stat-label">Servers</span>
                <span className="stat-value">{servers.length}</span>
              </div>
              <div className="stat-card">
                <span className="stat-label">Users</span>
                <span className="stat-value">{users.length}</span>
              </div>
              <div className="stat-card">
                <span className="stat-label">API Keys</span>
                <span className="stat-value">{keys.length}</span>
              </div>
            </div>
          </section>
        )}

        {/* SERVERS */}
        {activeTab === "servers" && (
          <section className="panel">
            <div className="panel-header">
              <h3>Registered Servers/DGX</h3>
              <button className="primary" onClick={() => setShowAddServer(true)}>+ Add Server</button>
            </div>

            {servers.length > 0 ? (
              <div className="table">
                <div className="table-row header">
                  <span>Hostname</span>
                  <span>Port</span>
                  <span>Status</span>
                  <span>Description</span>
                  <span>Actions</span>
                </div>
                {servers.map((server) => (
                  <div key={server.id} className="table-row">
                    <span>{server.hostname}</span>
                    <span>{server.port}</span>
                    <span>{server.last_ok ? "✅" : "❌"}</span>
                    <span>{server.description || "-"}</span>
                    <span>
                      <button className="danger" onClick={() => handleDeleteServer(server.id)}>Delete</button>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-message">No servers registered yet</p>
            )}

            {showAddServer && (
              <div className="dialog-overlay" onClick={() => setShowAddServer(false)}>
                <div className="dialog" onClick={(e) => e.stopPropagation()}>
                  <h4>Register Server</h4>
                  <form onSubmit={handleCreateServer}>
                    <input
                      placeholder="Hostname (e.g., dgx-01)"
                      value={newServer.hostname}
                      onChange={(e) => setNewServer({ ...newServer, hostname: e.target.value })}
                      required
                    />
                    <input
                      type="number"
                      placeholder="Port (e.g., 8000)"
                      value={newServer.port}
                      onChange={(e) => setNewServer({ ...newServer, port: e.target.value })}
                      required
                    />
                    <input
                      placeholder="Description (optional)"
                      value={newServer.description}
                      onChange={(e) => setNewServer({ ...newServer, description: e.target.value })}
                    />
                    <div className="dialog-buttons">
                      <button type="submit" className="primary">Register</button>
                      <button type="button" className="secondary" onClick={() => setShowAddServer(false)}>Cancel</button>
                    </div>
                  </form>
                </div>
              </div>
            )}
          </section>
        )}

        {/* MODELS */}

        {/* MODELS */}
        {activeTab === "models" && (
          <section className="panel">
            <div className="panel-header">
              <h3>Registered Models</h3>
              <button className="primary" onClick={() => setShowAddModel(true)}>+ Add Model</button>
            </div>

            {models.length > 0 ? (
              <div className="table">
                <div className="table-row header">
                  <span>Name</span>
                  <span>Backend</span>
                  <span>Status</span>
                  <span>Actions</span>
                </div>
                {models.map((model) => (
                  <div key={model.id} className="table-row">
                    <span>{model.name}</span>
                    <span>{model.backend_url}</span>
                    <span>{model.enabled ? "✅" : "❌"}</span>
                    <span>
                      <button className="danger" onClick={() => handleDeleteModel(model.id)}>Delete</button>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-message">No models registered yet</p>
            )}

            {showAddModel && (
              <div className="dialog-overlay" onClick={() => setShowAddModel(false)}>
                <div className="dialog" onClick={(e) => e.stopPropagation()}>
                  <h4>Register Model</h4>
                  <form onSubmit={handleCreateModel}>
                    <input
                      placeholder="Model name"
                      value={newModel.name}
                      onChange={(e) => setNewModel({ ...newModel, name: e.target.value })}
                      required
                    />
                    <input
                      placeholder="Backend host"
                      value={newModel.backend_host}
                      onChange={(e) => setNewModel({ ...newModel, backend_host: e.target.value })}
                      required
                    />
                    <input
                      type="number"
                      placeholder="Port"
                      value={newModel.backend_port}
                      onChange={(e) => setNewModel({ ...newModel, backend_port: e.target.value })}
                      required
                    />
                    <input
                      placeholder="Description"
                      value={newModel.description}
                      onChange={(e) => setNewModel({ ...newModel, description: e.target.value })}
                    />
                    <div className="dialog-buttons">
                      <button type="button" className="secondary" onClick={handleTestModel}>Test Endpoint</button>
                      <button type="submit" className="primary">Register</button>
                    </div>
                    {modelTestResult && (
                      <div className="test-result">
                        <p>{modelTestResult.ok ? "✅ Endpoint OK" : "❌ Failed: " + modelTestResult.error}</p>
                      </div>
                    )}
                    <button type="button" className="secondary" onClick={() => setShowAddModel(false)}>Close</button>
                  </form>
                </div>
              </div>
            )}
          </section>
        )}

        {/* USERS & KEYS */}
        {activeTab === "users" && (
          <section className="panel">
            <div className="panel-header">
              <h3>Users & API Keys</h3>
              <div className="button-group">
                <button className="primary" onClick={() => setShowAddUser(true)}>+ Add User</button>
                <button className="secondary" onClick={() => setShowAddKey(true)}>+ Add Key</button>
              </div>
            </div>

            <h4>Users</h4>
            {users.length > 0 ? (
              <div className="table">
                <div className="table-row header">
                  <span>Username</span>
                  <span>Email</span>
                  <span>Status</span>
                  <span>Actions</span>
                </div>
                {users.map((user) => (
                  <div key={user.id} className="table-row">
                    <span>{user.username}</span>
                    <span>{user.email || "-"}</span>
                    <span>{user.is_active ? "Active" : "Disabled"}</span>
                    <span>
                      <button className="danger" onClick={() => handleDeleteUser(user.id)}>Delete</button>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-message">No users yet</p>
            )}

            <h4 style={{ marginTop: "24px" }}>API Keys</h4>
            {keys.length > 0 ? (
              <div className="table">
                <div className="table-row header">
                  <span>Name</span>
                  <span>User</span>
                  <span>Key</span>
                  <span>Actions</span>
                </div>
                {keys.map((key) => (
                  <div key={key.id} className="table-row">
                    <span>{key.name}</span>
                    <span>{key.user_id}</span>
                    <span className="key-cell">{key.key.substring(0, 20)}...</span>
                    <span>
                      <button className="danger" onClick={() => handleDeleteKey(key.id)}>Delete</button>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-message">No API keys yet</p>
            )}

            {showAddUser && (
              <div className="dialog-overlay" onClick={() => setShowAddUser(false)}>
                <div className="dialog" onClick={(e) => e.stopPropagation()}>
                  <h4>Create User</h4>
                  <form onSubmit={handleCreateUser}>
                    <input
                      placeholder="Username"
                      value={newUser.username}
                      onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                      required
                    />
                    <input
                      placeholder="Email"
                      value={newUser.email}
                      onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                    />
                    <div className="dialog-buttons">
                      <button type="submit" className="primary">Create</button>
                      <button type="button" className="secondary" onClick={() => setShowAddUser(false)}>Cancel</button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            {showAddKey && (
              <div className="dialog-overlay" onClick={() => setShowAddKey(false)}>
                <div className="dialog" onClick={(e) => e.stopPropagation()}>
                  <h4>Create API Key</h4>
                  <form onSubmit={handleCreateKey}>
                    <label>Select User</label>
                    <select value={selectedUserForKey} onChange={(e) => setSelectedUserForKey(e.target.value)} required>
                      <option value="">-- Select User --</option>
                      {users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
                    </select>
                    <input
                      placeholder="Key Name"
                      value={newKeyName}
                      onChange={(e) => setNewKeyName(e.target.value)}
                      required
                    />
                    <div className="dialog-buttons">
                      <button type="submit" className="primary">Create</button>
                      <button type="button" className="secondary" onClick={() => setShowAddKey(false)}>Cancel</button>
                    </div>
                  </form>
                </div>
              </div>
            )}
          </section>
        )}

        {/* USAGE */}
        {activeTab === "usage" && (
          <section className="panel">
            <h3>Token Usage Logs</h3>
            {usageLogs.length > 0 ? (
              <div className="table">
                <div className="table-row header">
                  <span>Time</span>
                  <span>User</span>
                  <span>Model</span>
                  <span>Prompt</span>
                  <span>Completion</span>
                  <span>Total</span>
                </div>
                {usageLogs.map((entry) => (
                  <div key={entry.id} className="table-row">
                    <span>{entry.timestamp ? new Date(entry.timestamp).toLocaleString() : "-"}</span>
                    <span>{entry.username || "-"}</span>
                    <span>{entry.model || "-"}</span>
                    <span>{(entry.prompt_tokens || 0).toLocaleString()}</span>
                    <span>{(entry.completion_tokens || 0).toLocaleString()}</span>
                    <span>{(entry.total_tokens || 0).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-message">No usage data</p>
            )}
          </section>
        )}

        {activeTab === "test" && (
          <section className="panel">
            <h3>Test Gateway</h3>
            <div className="form-grid">
              <input placeholder="API Key" value={testState.apiKey} onChange={(e) => setTestState({ ...testState, apiKey: e.target.value })} />
              <input placeholder="Model" value={testState.model} onChange={(e) => setTestState({ ...testState, model: e.target.value })} />
            </div>
            <textarea rows="4" value={testState.message} onChange={(e) => setTestState({ ...testState, message: e.target.value })} />
            <button onClick={handleGatewayTest}>Send Request</button>

            {testResponse && (
              <div className="panel">
                <h4>Response</h4>
                <pre>{JSON.stringify(testResponse, null, 2)}</pre>
              </div>
            )}
          </section>
        )}

        {activeTab === "ops" && (
          <section className="panel-grid">
            <div className="panel">
              <h3>Gateway Lifecycle</h3>
              <p>Start/Stop/Reset the APISIX stack from the UI.</p>
              <div className="inline">
                <button className="secondary" onClick={async () => setOpsStatus(await api.manager.opsStatus())}>Status</button>
                <button onClick={async () => setOpsStatus(await api.manager.opsDeploy())}>Start Gateway</button>
                <button className="danger" onClick={async () => setOpsStatus(await api.manager.opsStop())}>Stop</button>
                <button className="danger" onClick={async () => setOpsStatus(await api.manager.opsReset())}>Cold Reset</button>
              </div>
              {opsStatus && (
                <div className="panel">
                  <h4>Output</h4>
                  <pre>{opsStatus.stdout || opsStatus.stderr || "(no output)"}</pre>
                </div>
              )}
            </div>

            <div className="panel">
              <h3>Environment Variables</h3>
              <p>Update gateway/manager configuration without CLI.</p>
              <button className="secondary" onClick={async () => {
                const data = await api.manager.getEnv();
                setEnvValues(data.values || {});
              }}>Load .env</button>

              <div className="form-grid" style={{ marginTop: 12 }}>
                {Object.entries(envValues).map(([key, value]) => (
                  <label key={key}>
                    {key}
                    <input
                      value={value}
                      onChange={(e) => setEnvValues({ ...envValues, [key]: e.target.value })}
                    />
                  </label>
                ))}
              </div>

              <button onClick={async () => setOpsStatus(await api.manager.updateEnv(envValues))}>Save .env</button>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
