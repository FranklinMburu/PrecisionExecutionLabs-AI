import express from "express";
import { createServer as createViteServer } from "vite";
import { spawn } from "child_process";
import path from "path";

async function startServer() {
  const app = express();
  const PORT = 3000;

  console.log("🚀 Starting MT5 Trading Engine (Python)...");
  
  // Robust python detection
  const pythonCmd = process.platform === "win32" ? "python" : "python3";
  
  const pythonProcess = spawn(pythonCmd, ["main.py"], {
    stdio: "inherit",
    env: { ...process.env, PYTHONUNBUFFERED: "1" }
  });

  pythonProcess.on("error", (err) => {
    console.error("❌ Failed to start Python engine:", err);
  });

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { 
        middlewareMode: true,
        proxy: {
          '/api': {
            target: 'http://localhost:8000',
            changeOrigin: true,
          }
        }
      },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`✨ Dashboard ready at http://localhost:${PORT}`);
  });
}

startServer();
