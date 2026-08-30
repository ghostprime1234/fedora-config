const button = document.getElementById("run");
const status = document.getElementById("status");

button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Running folder sync...";

  try {
    const result = await messenger.runtime.sendMessage({
      command: "run_sync"
    });

    if (!result) {
      throw new Error("Background script returned no response.");
    }

    if (result.ok) {
      status.textContent = `SUCCESS\n\n${result.message}`;
    } else {
      status.textContent =
        `FAILED\n\n${result.message}` +
        (result.stack ? `\n\n${result.stack}` : "");
    }
  } catch (error) {
    status.textContent =
      `EXTENSION ERROR\n\n${error?.message || String(error)}`;
  } finally {
    button.disabled = false;
  }
});
