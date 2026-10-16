// EDITH.exe (Fase 15.1): lanzador nativo sin consola.
// Abre desktop/desktop_app.py con el pythonw.exe del entorno .venv del proyecto.
// En la Fase 15.3 lo reemplaza el ejecutable empaquetado con PyInstaller.
// Se compila con desktop\launcher\build_launcher.bat (usa el compilador C# que trae Windows).
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("EDITH")]
[assembly: AssemblyProduct("EDITH")]
[assembly: AssemblyDescription("EDITH - asistente de IA local")]
[assembly: AssemblyVersion("0.0.6.0")]

static class Launcher
{
    [STAThread]
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string pythonw = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        string app = Path.Combine(root, "desktop", "desktop_app.py");

        if (!File.Exists(pythonw))
        {
            MessageBox.Show("No encontré el entorno de Python de EDITH:\n" + pythonw +
                            "\n\nCrea el entorno con: python -m venv .venv  y luego  .venv\\Scripts\\pip install -r requirements.txt",
                            "EDITH", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        if (!File.Exists(app))
        {
            MessageBox.Show("Falta " + app, "EDITH", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        // Reenvía los argumentos (p. ej. --tray al iniciar con Windows)
        string extra = "";
        foreach (string a in args) extra += " \"" + a.Replace("\"", "") + "\"";
        var psi = new ProcessStartInfo(pythonw, "\"" + app + "\"" + extra);
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        Process.Start(psi);
        return 0;
    }
}
