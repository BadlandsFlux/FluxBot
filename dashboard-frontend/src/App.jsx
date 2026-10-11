import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import TopBar from "./components/TopBar";
import { FlashProvider } from "./components/Flash";
import Spinner from "./components/Spinner";
import { GuildsProvider } from "./context/GuildsContext";
import Login from "./pages/Login";
import GuildPicker from "./pages/GuildPicker";
import GuildDetail from "./pages/GuildDetail";
import ReportDetail from "./pages/ReportDetail";
import Commands from "./pages/Commands";
import Status from "./pages/Status";
import OwnerSettings from "./pages/OwnerSettings";
import { api, setUnauthorizedHandler } from "./api";

export default function App() {
  const [me, setMe] = useState(undefined); // undefined = loading, {user: null} = logged out

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe({ user: null, bot_name: "FluxBot" }));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe((prev) => ({ user: null, bot_name: prev?.bot_name || "FluxBot" })));
    return () => setUnauthorizedHandler(null);
  }, []);

  if (me === undefined) {
    return (
      <div className="boot-loading">
        <Spinner size={22} />
      </div>
    );
  }

  const botName = me.bot_name || "FluxBot";

  return (
    <BrowserRouter>
      <FlashProvider>
        <GuildsProvider enabled={!!me.user}>
          <TopBar user={me.user} isOwner={!!me.is_owner} botName={botName}
                  onLoggedOut={() => setMe({ user: null, bot_name: botName })} />
          <main className="content">
            <Routes>
              <Route path="/" element={me.user ? <GuildPicker /> : <Login botName={botName} />} />
              <Route path="/guild/:id" element={me.user ? <GuildDetail /> : <Login botName={botName} />} />
              <Route
                path="/guild/:id/reports/:reportId"
                element={me.user ? <ReportDetail /> : <Login botName={botName} />}
              />
              <Route path="/commands" element={<Commands />} />
              <Route path="/status" element={<Status />} />
              <Route
                path="/owner-settings"
                element={me.user && me.is_owner ? <OwnerSettings /> : <Login botName={botName} />}
              />
              {/* Old standalone routes, kept as redirects so existing bookmarks/links still land somewhere useful. */}
              <Route path="/bot-profile" element={<Navigate to="/owner-settings?tab=bot-profile" replace />} />
              <Route path="/discord-relay-setup" element={<Navigate to="/owner-settings?tab=discord-relay" replace />} />
              <Route path="/fluxer-status" element={<Navigate to="/owner-settings?tab=fluxer-status" replace />} />
            </Routes>
          </main>
        </GuildsProvider>
      </FlashProvider>
    </BrowserRouter>
  );
}

