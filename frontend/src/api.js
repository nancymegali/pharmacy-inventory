
const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export async function apiFetch(path, options = {}) {
  const token = sessionStorage.getItem("medstock_token");

  const headers = {
    ...options.headers,
  };

  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401 && token) {
    sessionStorage.removeItem("medstock_token");
    sessionStorage.removeItem("medstock_demo");

    window.dispatchEvent(new Event("medstock:session-expired"));
  }

  return response;
}

export { API_URL };
