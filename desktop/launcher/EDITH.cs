// EDITH.exe (Fase 15.1): lanzador nativo sin consola PARA EL MODO DESARROLLO.
// Abre desktop/desktop_app.py con el pythonw.exe del entorno .venv del proyecto.
// La app instalable es otra: dist\EDITH\EDITH.exe, empaquetada con PyInstaller (Fase 15.3,
// build\build_setup.ps1), que no necesita la carpeta del proyecto ni el .venv.
// Se compila con desktop\launcher\build_launcher.bat (usa el compilador C# que trae Windows);
// la versión sale del archivo VERSION de la raíz (el .bat genera los atributos de versión).
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("EDITH")]
[assembly: AssemblyProduct("EDITH")]
[assembly: AssemblyDescription("EDITH - asistente de IA local")]

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
