import http from "k6/http";
import { check, sleep } from "k6";

export const options = { stages: [{ duration: "20s", target: 10 }, { duration: "40s", target: 30 }, { duration: "10s", target: 0 }], thresholds: { http_req_failed: ["rate<0.01"], http_req_duration: ["p(95)<500"] } };

export default function () {
  const login = http.post("http://localhost:5173/api/v1/auth/token", { username: "admin@opspulse.local", password: "ChangeMe123!" });
  check(login, { "login succeeded": (r) => r.status === 200 });
  const token = login.json("access_token");
  const incidents = http.get("http://localhost:5173/api/v1/incidents", { headers: { Authorization: `Bearer ${token}` } });
  check(incidents, { "incidents listed": (r) => r.status === 200 });
  sleep(1);
}
