(() => {
  const editor = document.querySelector("#season-editor");
  if (!editor) return;
  let seasonIndex = Number(editor.dataset.nextSeason || "1");
  const label = (name) => editor.dataset[name];
  const episodeMarkup = (si, ei) => `<fieldset data-episode-index="${ei}">
    <legend>${label("episode")}</legend>
    <label>${label("episodeNumber")} <input name="season_${si}_episode_${ei}_number" type="number" min="1" required></label>
    <label>${label("episodeTitle")} <input name="season_${si}_episode_${ei}_title" required></label>
    <label>${label("episodePlot")} <textarea name="season_${si}_episode_${ei}_plot"></textarea></label>
    <button type="button" data-action="remove-episode">${label("removeEpisode")}</button></fieldset>`;

  editor.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    if (button.dataset.action === "add-season") {
      const si = seasonIndex++;
      const wrapper = document.createElement("fieldset");
      wrapper.dataset.seasonIndex = String(si);
      wrapper.dataset.nextEpisode = "1";
      wrapper.innerHTML = `<legend>${label("season")}</legend>
        <label>${label("seasonNumber")} <input name="season_${si}_number" type="number" min="0" required></label>
        <label>${label("seasonTitle")} <input name="season_${si}_title"></label>
        <div data-episodes>${episodeMarkup(si, 0)}</div>
        <button type="button" data-action="add-episode">${label("addEpisode")}</button>
        <button type="button" data-action="remove-season">${label("removeSeason")}</button>`;
      button.before(wrapper);
      wrapper.querySelector("input").focus();
    } else if (button.dataset.action === "add-episode") {
      const season = button.closest("[data-season-index]");
      const ei = Number(season.dataset.nextEpisode || "1");
      season.dataset.nextEpisode = String(ei + 1);
      const episodes = season.querySelector("[data-episodes]");
      episodes.insertAdjacentHTML(
        "beforeend", episodeMarkup(season.dataset.seasonIndex, ei)
      );
      episodes.lastElementChild.querySelector("input").focus();
    } else if (button.dataset.action === "remove-season") {
      button.closest("[data-season-index]").remove();
    } else if (button.dataset.action === "remove-episode") {
      button.closest("[data-episode-index]").remove();
    }
  });
})();
