import { useSearchParams } from "react-router-dom";
import { Zap } from "lucide-react";

const ERROR_MESSAGES = {
  state_mismatch: "Login failed (state mismatch). Try again.",
  oauth_failed: "Fluxer rejected that login. Try again.",
};

export default function Login({ botName }) {
  const [params] = useSearchParams();
  const errorCode = params.get("login_error");
  const errorMessage = errorCode ? ERROR_MESSAGES[errorCode] || "Login failed. Try again." : null;

  return (
    <div className="card center-card">
      <div className="center-card-icon">
        <Zap size={24} strokeWidth={2.5} />
      </div>
      <h1>{botName}</h1>
      <p className="muted">Sign in to manage moderation, autoroles, and reaction roles for your servers.</p>
      {errorMessage && <p className="error">{errorMessage}</p>}
      <a className="btn btn-primary btn-wide" href="/login">
        Login with Fluxer
      </a>
    </div>
  );
}
