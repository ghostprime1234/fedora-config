const HOST = "unisq_mail_sync";

async function findAccount(email) {
  const wanted = email.toLowerCase();
  const accounts = await messenger.accounts.list(true);

  for (const account of accounts) {
    for (const identity of account.identities || []) {
      if ((identity.email || "").toLowerCase() === wanted) {
        return account;
      }
    }
  }

  throw new Error(`Could not find Betterbird account for ${email}`);
}

async function findChild(parentId, name) {
  const parent = await messenger.folders.get(parentId, true);
  return (parent.subFolders || []).find(folder => folder.name === name) || null;
}

async function ensurePath(rootId, path) {
  let parentId = rootId;

  for (const part of path.split("/").filter(Boolean)) {
    let child = await findChild(parentId, part);

    if (!child) {
      child = await messenger.folders.create(parentId, part);
    }

    parentId = child.id;
  }
}

async function syncFolders() {
  const request = await messenger.runtime.sendNativeMessage(HOST, {
    command: "get_request"
  });

  if (!request?.account_email || !Array.isArray(request.folders)) {
    throw new Error("Invalid folder request from native host.");
  }

  const account = await findAccount(request.account_email);

  const folders = [...request.folders].sort(
    (a, b) =>
      a.split("/").length - b.split("/").length ||
      a.localeCompare(b)
  );

  for (const path of folders) {
    await ensurePath(account.rootFolder.id, path);
  }

  try {
    await messenger.runtime.sendNativeMessage(HOST, {
      command: "write_status",
      status: {
        ok: true,
        checked_count: folders.length,
        completed_at: new Date().toISOString()
      }
    });
  } catch (error) {
    console.warn("Folders created, but status write failed:", error);
  }

  return {
    ok: true,
    message: `Folder sync completed successfully. Checked ${folders.length} folder paths.`
  };
}

messenger.runtime.onMessage.addListener(async message => {
  if (message?.command !== "run_sync") {
    return;
  }

  try {
    return await syncFolders();
  } catch (error) {
    console.error("UniSQ folder sync failed:", error);

    return {
      ok: false,
      message: error?.message || String(error),
      stack: error?.stack || ""
    };
  }
});

messenger.action.onClicked.addListener(async () => {
  try {
    await messenger.runtime.openOptionsPage();
  } catch (error) {
    console.error("Could not open UniSQ Folder Sync options:", error);
  }
});
