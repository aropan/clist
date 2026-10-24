function init_account_buttons() {
  $("#accounts .add-account, #accounts .delete-account").click(function (e) {
    e.preventDefault();
    $btn = $(this);
    $btn.toggleClass("hidden");
    $loading = $(this).parent().find(".loading-account");
    $loading.toggleClass("hidden");
    $.ajax({
      type: "POST",
      url: change_url,
      data: {
        pk: coder_pk,
        name: $btn.attr("data-action"),
        id: $btn.attr("data-id"),
      },
      success: function (data) {
        $btn.parent().children().toggleClass("hidden");
        $btn.toggleClass("hidden");
        $btn.closest("tr").toggleClass("info");
        notify($btn.attr("data-message"), "success");
      },
      error: function (response) {
        if (response.responseJSON && response.responseJSON.message == "redirect") {
          window.location.replace(response.responseJSON.url);
          return;
        }
        $loading.toggleClass("hidden");
        $btn.toggleClass("hidden");
        log_ajax_error(response);
      },
    });
  });
}

function init_clickable_has_coders() {
  $(".has_coders.clickable").click(function (e) {
    var checkbox = $(this).next();
    checkbox.removeClass("hidden");
    checkbox.click();
    $(this).remove();
  });
}

function invert_accounts(e, s) {
  e.preventDefault();
  $('#accounts input[name="' + $.escapeSelector(s) + '"]').click();
}

var account_renaming = null;

function account_renaming_data(checkbox) {
  return {
    id: checkbox.value,
    resource: checkbox.dataset.resource,
    host: checkbox.dataset.host,
    key: checkbox.dataset.key,
    name: checkbox.dataset.name,
  };
}

function init_account_renaming_rows() {
  if (!account_renaming) return;
  const selected = account_renaming.selected;
  const active = account_renaming.active || selected.size > 0;
  const wasActive = $("#accounts").hasClass("account-renaming-active");
  $("#accounts").toggleClass("account-renaming-active", active);
  $("#account-renaming").toggleClass("hidden", !active);
  $("#account-renaming-toggle-group").toggleClass("hidden", active);
  $("#account-renaming-toggle").attr("aria-expanded", String(active));
  const resource = selected.size ? selected.values().next().value.resource : account_renaming.invertResource;
  const checkboxes = $("#accounts .account-renaming-select");
  checkboxes.each(function () {
    const checked = selected.has(this.value);
    $(this)
      .prop("checked", checked)
      .prop("disabled", resource !== null && this.dataset.resource !== resource);
    $(this).closest("tr").toggleClass("account-merge-selected", checked);
  });

  const resources = new Set(checkboxes.map((_, checkbox) => checkbox.dataset.resource).get());
  const eligible = checkboxes.filter((_, checkbox) => resource === null || checkbox.dataset.resource === resource);
  $("#account-renaming-invert").prop("disabled", !eligible.length || (resource === null && resources.size > 1));
  $("#account-renaming-count")
    .text(`Merge: ${selected.size}`)
    .parent()
    .attr(
      "data-original-title",
      `${selected.size ? `Selected on ${selected.values().next().value.host}.` : "Select accounts from one resource."} Selection is kept across searches in this tab.`,
    );
  $("#account-renaming-review").prop("disabled", selected.size < 2);
  if (active !== wasActive) $(window).trigger("resize");
}

function save_account_renaming_selection() {
  try {
    sessionStorage.setItem(account_renaming.storageKey, JSON.stringify([...account_renaming.selected.values()]));
  } catch (_error) {
    $("#account-renaming-error").text(
      "Selection could not be saved for the next search. Merge before leaving this page.",
    );
  }
  init_account_renaming_rows();
}

function review_account_renaming() {
  $("#account-renaming-review").tooltip("hide");
  const selected = account_renaming.selected;
  let targetId = null;
  let pending = false;
  const content = $("<div>");
  $("<p>")
    .text(
      "Choose the account to keep. All other selected accounts will be renamed into it, including related accounts.",
    )
    .appendTo(content);
  const choices = $("<div>", { class: "account-renaming-choices" }).appendTo(content);
  const summary = $("<p>", { class: "account-renaming-summary", "aria-live": "polite" }).appendTo(content);
  const error = $("<div>", { class: "text-danger", role: "alert" }).appendTo(content);
  const dialog = bootbox.dialog({
    title: "Merge accounts",
    message: content,
    closeButton: false,
    onEscape: () => !pending,
    buttons: {
      cancel: {
        label: "Cancel",
        className: "btn-default",
        callback: () => !pending,
      },
      confirm: {
        label: "Rename into selected account",
        className: "btn-warning",
        callback: function () {
          if (pending || !targetId || selected.size < 2) return false;
          pending = true;
          error.empty();
          dialog.find("button, input").prop("disabled", true);
          $.ajax({
            type: "POST",
            url: account_renaming.url,
            traditional: true,
            data: { accounts: [...selected.keys()], target: targetId },
            success: function (data) {
              selected.clear();
              account_renaming.active = false;
              account_renaming.invertResource = null;
              save_account_renaming_selection();
              dialog.modal("hide");
              notify(data.message, "success");
              window.location.reload();
            },
            error: function (response) {
              pending = false;
              error.text(
                response.responseJSON?.message || "Could not merge accounts. Refresh the page before retrying.",
              );
              dialog.find("button, input").prop("disabled", false);
              update_summary();
            },
          });
          return false;
        },
      },
    },
  });
  dialog.removeAttr("aria-hidden").attr({ "aria-modal": "true", "aria-labelledby": "account-renaming-title" });
  dialog.find(".modal-title").attr("id", "account-renaming-title");

  function update_summary() {
    const target = selected.get(targetId);
    dialog.find(".bootbox-accept").prop("disabled", !target || selected.size < 2);
    summary.text(
      target
        ? `${selected.size - 1} account(s) → ${target.key} on ${target.host}. This account will be kept.`
        : "Select the account to keep to continue.",
    );
    choices.find(".account-renaming-choice").each(function () {
      $(this).toggleClass("account-renaming-target", $(this).find("input").val() === targetId);
    });
  }

  function render_choices() {
    choices.empty();
    selected.forEach((account) => {
      const row = $("<div>", { class: "account-renaming-choice" }).appendTo(choices);
      const label = $("<label>").appendTo(row);
      $("<input>", {
        type: "radio",
        name: "account-renaming-target",
        value: account.id,
        checked: account.id === targetId,
        "aria-label": `Keep ${account.key} on ${account.host}`,
      })
        .on("change", function () {
          targetId = this.value;
          update_summary();
        })
        .appendTo(label);
      const details = $("<span>").appendTo(label);
      $("<strong>").text(account.key).appendTo(details);
      $("<small>", { class: "text-muted" })
        .text(`${account.name && account.name !== account.key ? `${account.name} · ` : ""}${account.host}`)
        .appendTo(details);
      $("<button>", {
        type: "button",
        class: "btn btn-default btn-xs",
        text: "Deselect",
        "aria-label": `Deselect ${account.key}`,
      })
        .on("click", function () {
          selected.delete(account.id);
          account_renaming.invertResource = null;
          if (targetId === account.id) targetId = null;
          if (!selected.size) account_renaming.active = false;
          save_account_renaming_selection();
          if (selected.size) render_choices();
          else dialog.modal("hide");
        })
        .appendTo(row);
    });
    update_summary();
  }
  render_choices();
}

$(function () {
  const panel = $("#account-renaming");
  if (!panel.length) return;
  account_renaming = {
    active: false,
    invertResource: null,
    selected: new Map(),
    storageKey: panel.attr("data-storage-key"),
    limit: Number(panel.attr("data-limit")),
    url: panel.attr("data-url"),
  };
  try {
    const saved = JSON.parse(sessionStorage.getItem(account_renaming.storageKey) || "[]");
    if (Array.isArray(saved)) {
      saved.slice(0, account_renaming.limit).forEach((account) => {
        if (
          account &&
          [account.id, account.resource, account.host, account.key].every((value) => typeof value === "string")
        ) {
          account_renaming.selected.set(account.id, account);
        }
      });
    }
  } catch (_error) {
    // Selection still works when session storage is unavailable.
  }
  account_renaming.active = account_renaming.selected.size > 0;
  if (account_renaming.active && $("#filter-toggle").is(":visible")) $("#filter-collapse").collapse("show");

  $("#account-renaming-toggle").on("click", function () {
    $(this).tooltip("hide");
    account_renaming.active = true;
    init_account_renaming_rows();
  });
  $("#accounts").on("change", ".account-renaming-select", function () {
    $("#account-renaming-error").empty();
    account_renaming.invertResource = null;
    if (this.checked) {
      if (account_renaming.selected.size >= account_renaming.limit) {
        $("#account-renaming-error").text(`Select up to ${account_renaming.limit} accounts at a time.`);
      } else {
        account_renaming.selected.set(this.value, account_renaming_data(this));
      }
    } else {
      account_renaming.selected.delete(this.value);
    }
    save_account_renaming_selection();
  });
  $("#account-renaming-invert").on("click", function () {
    $(this).tooltip("hide");
    $("#account-renaming-error").empty();
    const selected = account_renaming.selected;
    const accounts = new Map();
    $("#accounts .account-renaming-select:enabled").each(function () {
      accounts.set(this.value, account_renaming_data(this));
    });
    let count = selected.size;
    accounts.forEach((_account, id) => {
      count += selected.has(id) ? -1 : 1;
    });
    if (count > account_renaming.limit) {
      $("#account-renaming-error").text(`Select up to ${account_renaming.limit} accounts at a time.`);
      return;
    }
    // Keep the resource when inversion clears the selection so the next click can restore it.
    account_renaming.invertResource = accounts.size ? accounts.values().next().value.resource : null;
    accounts.forEach((account, id) => {
      if (selected.has(id)) selected.delete(id);
      else selected.set(id, account);
    });
    save_account_renaming_selection();
  });
  $("#account-renaming-clear").on("click", function () {
    $(this).tooltip("hide");
    account_renaming.active = false;
    account_renaming.invertResource = null;
    account_renaming.selected.clear();
    $("#account-renaming-error").empty();
    save_account_renaming_selection();
  });
  $("#account-renaming-review").on("click", review_account_renaming);
  init_account_renaming_rows();
});
