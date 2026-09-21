/* Shared SPA navigation helper.

   The application is a lightweight history-based router: AppNavigation owns
   the popstate listener and re-resolves the current page.  Pushing a path and
   dispatching a popstate keeps deep links (including query strings) working
   without a full page reload. */

export const navigateTo = (path) => {
    if (typeof window === "undefined" || !path) return;
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
};
