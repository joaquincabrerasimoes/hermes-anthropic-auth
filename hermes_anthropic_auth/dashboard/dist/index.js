(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useCallback = SDK.hooks.useCallback;
  var C = SDK.components;

  var API = "/api/plugins/hermes-anthropic-auth";

  function fetchJSON(path, options) {
    return SDK.fetchJSON(path, options);
  }

  function AnthropicAuthPage() {
    var profileState = useState("default");
    var profile = profileState[0];
    var setProfile = profileState[1];

    var profilesState = useState([{ name: "default" }]);
    var profiles = profilesState[0];
    var setProfiles = profilesState[1];

    var statusState = useState(null);
    var status = statusState[0];
    var setStatus = statusState[1];

    var authorizeUrlState = useState(null);
    var authorizeUrl = authorizeUrlState[0];
    var setAuthorizeUrl = authorizeUrlState[1];

    var codeStateState = useState("");
    var codeState = codeStateState[0];
    var setCodeState = codeStateState[1];

    var busyState = useState(false);
    var busy = busyState[0];
    var setBusy = busyState[1];

    var messageState = useState(null);
    var message = messageState[0];
    var setMessage = messageState[1];

    var loadProfiles = useCallback(function () {
      fetchJSON(API + "/profiles")
        .then(function (data) {
          var list = (data && data.profiles && data.profiles.length) ? data.profiles : [{ name: "default" }];
          setProfiles(list);
        })
        .catch(function () {
          setProfiles([{ name: "default" }]);
        });
    }, []);

    var loadStatus = useCallback(function (p) {
      fetchJSON(API + "/status?profile=" + encodeURIComponent(p))
        .then(function (data) {
          setStatus(data);
        })
        .catch(function () {
          setStatus(null);
        });
    }, []);

    useEffect(function () {
      loadProfiles();
    }, [loadProfiles]);

    useEffect(function () {
      loadStatus(profile);
    }, [profile, loadStatus]);

    function startLogin() {
      setBusy(true);
      setMessage(null);
      fetchJSON(API + "/oauth/start", { method: "POST" })
        .then(function (data) {
          setBusy(false);
          if (data && data.authorize_url) {
            setAuthorizeUrl(data.authorize_url);
            window.open(data.authorize_url, "_blank", "noopener,noreferrer");
          } else {
            setMessage({ type: "error", text: (data && data.error) || "Could not start login." });
          }
        })
        .catch(function (err) {
          setBusy(false);
          setMessage({ type: "error", text: "Could not start login: " + err });
        });
    }

    function completeLogin() {
      var trimmed = (codeState || "").trim();
      if (!trimmed) return;
      setBusy(true);
      setMessage(null);
      fetchJSON(API + "/oauth/complete", {
        method: "POST",
        body: JSON.stringify({ code_state: trimmed, profile: profile }),
      })
        .then(function (data) {
          setBusy(false);
          if (data && data.ok) {
            setMessage({ type: "success", text: 'Logged in and bound to profile "' + profile + '".' });
            setCodeState("");
            setAuthorizeUrl(null);
            loadStatus(profile);
          } else {
            setMessage({ type: "error", text: (data && data.error) || "Login failed." });
          }
        })
        .catch(function (err) {
          setBusy(false);
          setMessage({ type: "error", text: "Login failed: " + err });
        });
    }

    var children = [];

    children.push(
      React.createElement(
        "p",
        { key: "intro", className: "text-sm text-muted-foreground" },
        "Log in with a Claude Pro/Max subscription and bind the credential to a Hermes profile. " +
          "Uses the same PKCE login Anthropic's own CLI uses \u2014 no API key needed."
      )
    );

    children.push(
      React.createElement(
        "div",
        { key: "profile-picker", className: "space-y-1" },
        React.createElement(C.Label, null, "Profile"),
        React.createElement(
          C.Select,
          { value: profile, onValueChange: setProfile },
          profiles.map(function (p) {
            return React.createElement(C.SelectOption, { key: p.name, value: p.name }, p.name);
          })
        )
      )
    );

    if (status) {
      var expiresChild = null;
      if (status.entries && status.entries[0] && status.entries[0].expires_at_ms) {
        expiresChild = React.createElement(
          "span",
          { className: "text-xs text-muted-foreground" },
          "Token expires " + new Date(status.entries[0].expires_at_ms).toLocaleString()
        );
      }
      children.push(
        React.createElement(
          "div",
          { key: "status", className: "flex items-center gap-2" },
          React.createElement(
            C.Badge,
            { variant: status.connected ? "default" : "secondary" },
            status.connected ? "Connected" : "Not connected"
          ),
          expiresChild
        )
      );
    }

    children.push(
      React.createElement(
        C.Button,
        { key: "login-btn", onClick: startLogin, disabled: busy },
        "Login with Claude"
      )
    );

    if (authorizeUrl) {
      children.push(
        React.createElement(
          "div",
          { key: "code-entry", className: "space-y-2 border-t pt-4" },
          React.createElement(
            "p",
            { className: "text-sm" },
            "A new tab opened to Anthropic. After approving, copy the code Anthropic shows you " +
              "(looks like CODE#STATE) and paste it below."
          ),
          React.createElement(C.Input, {
            placeholder: "paste CODE#STATE here",
            value: codeState,
            onChange: function (e) {
              setCodeState(e.target.value);
            },
          }),
          React.createElement(
            C.Button,
            { onClick: completeLogin, disabled: busy || !codeState.trim() },
            "Complete Login"
          )
        )
      );
    }

    if (message) {
      children.push(
        React.createElement(
          "p",
          {
            key: "message",
            className: message.type === "error" ? "text-sm text-destructive" : "text-sm text-green-600",
          },
          message.text
        )
      );
    }

    return React.createElement(
      C.Card,
      null,
      React.createElement(
        C.CardHeader,
        null,
        React.createElement(C.CardTitle, null, "Anthropic OAuth (Claude Pro/Max)")
      ),
      React.createElement(C.CardContent, { className: "space-y-4" }, children)
    );
  }

  window.__HERMES_PLUGINS__.register("hermes-anthropic-auth", AnthropicAuthPage);
})();
