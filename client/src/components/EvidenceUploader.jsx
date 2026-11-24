export function EvidenceUploader({ onFile }) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const file = event.currentTarget.elements.evidence.files[0];
        if (file) onFile(file);
      }}
    >
      <input name="evidence" type="file" aria-label="Evidence file" />
      <button type="submit">Upload evidence</button>
    </form>
  );
}
