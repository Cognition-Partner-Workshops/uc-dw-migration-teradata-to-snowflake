import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { initApi } from "./api/client";
import "./styles.css";

initApi().then(() =>
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  ),
);
