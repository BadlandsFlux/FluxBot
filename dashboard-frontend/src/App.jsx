import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import TopBar from "./components/TopBar";
import { FlashProvider } from "./components/Flash";
import Spinner from "./components/Spinner";
import { GuildsProvider } from "./context/GuildsContext";
import Login from "./pages/Login";
import GuildPicker from "./pages/GuildPicker";
import GuildDetail from "./pages/GuildDetail";
import Commands from "./pages/Commands";
import Status from "./pages/Status";
import { api } from "./api";

export default function App() {
  const [me, setMe] = useState(undefined); // undefined = loading, {user: null} = logged out

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe({ user: null, bot_name: "FluxBot" }));
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
          <TopBar user={me.user} botName={botName} onLoggedOut={() => setMe({ user: null, bot_name: botName })} />
          <main className="content">
            <Routes>
              <Route path="/" element={me.user ? <GuildPicker /> : <Login botName={botName} />} />
              <Route path="/guild/:id" element={me.user ? <GuildDetail /> : <Login botName={botName} />} />
              <Route path="/commands" element={<Commands />} />
              <Route path="/status" element={<Status />} />
            </Routes>
          </main>
        </GuildsProvider>
      </FlashProvider>
    </BrowserRouter>
  );
}

