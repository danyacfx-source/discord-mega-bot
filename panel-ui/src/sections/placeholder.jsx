export default function Placeholder({ section }) {
  return (
    <div class="placeholder">
      <div class="placeholder-art">{section.icon}</div>
      <h2>{section.title}</h2>
      <p class="muted">{section.desc}</p>
      <div class="placeholder-note">Раздел пока не перенесён в новый интерфейс.</div>
    </div>
  );
}
