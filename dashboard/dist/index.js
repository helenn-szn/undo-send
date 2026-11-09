(function () {
  var SDK = window.__HERMES_PLUGIN_SDK__ || {};
  var React = SDK.React || window.React;
  var h = React.createElement;
  var BASE = "/api/plugins/undo-send";

  function api(path, method) {
    var get = SDK.fetchJSON;
    if (get && (!method || method === "GET")) return get(BASE + path);
    return fetch(BASE + path, { method: method || "GET" }).then(function (r) { return r.json(); });
  }

  var COLORS = { pending: "#f59e0b", sending: "#3b82f6", sent: "#22c55e", cancelled: "#a1a1aa", failed: "#ef4444" };

  function Row(props) {
    var it = props.item;
    return h("div", {
      style: { display: "flex", gap: 12, alignItems: "center", padding: "10px 12px",
               borderBottom: "1px solid rgba(127,127,127,.2)", fontSize: 13 }
    },
      h("span", { style: { color: COLORS[it.status] || "inherit", fontWeight: 600, minWidth: 82 } }, it.status),
      h("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, it.summary),
      it.status === "pending" && h("span", { style: { opacity: .7, fontVariantNumeric: "tabular-nums" } },
        Math.ceil(it.seconds_left) + "s"),
      it.status === "pending" && h("button", { onClick: function () { api("/unsend/" + it.id, "POST").then(props.refresh); } }, "Undo"),
      it.status === "pending" && h("button", { onClick: function () { api("/sendnow/" + it.id, "POST").then(props.refresh); } }, "Send now")
    );
  }

  function Page() {
    var s = React.useState([]), items = s[0], setItems = s[1];
    function refresh() { api("/recent?limit=30").then(function (d) { setItems(d.items || []); }).catch(function () {}); }
    React.useEffect(function () { refresh(); var t = setInterval(refresh, 1000); return function () { clearInterval(t); }; }, []);
    return h("div", { style: { padding: 24, maxWidth: 900 } },
      h("h2", { style: { margin: "0 0 4px" } }, "Undo Send"),
      h("p", { style: { opacity: .7, margin: "0 0 16px" } },
        "Messages, posts, tickets and pushes wait here for a few seconds before they run."),
      items.length ? items.map(function (it) { return h(Row, { key: it.id, item: it, refresh: refresh }); })
                   : h("p", { style: { opacity: .6 } }, "Nothing held yet.")
    );
  }

  window.__HERMES_PLUGINS__.register("undo-send", Page);
})();
