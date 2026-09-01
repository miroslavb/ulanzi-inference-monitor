// Pure provider-list editor model shared by the Property Inspector UI.
// Loaded as a classic script because Ulanzi Studio injects its PI API as globals.
(function exposeProviderOrder(root) {
  function providerList(providers) {
    const seen = new Set();
    const list = [];
    for (const provider of Array.isArray(providers) ? providers : []) {
      const id = provider && typeof provider.id === 'string' ? provider.id.trim() : '';
      if (!id || seen.has(id)) continue;
      seen.add(id);
      list.push({ ...provider, id });
    }
    return list;
  }

  function selected(providers, savedIds) {
    const list = providerList(providers);
    const available = new Set(list.map((provider) => provider.id));
    if (!Array.isArray(savedIds)) return list.map((provider) => provider.id);

    const seen = new Set();
    const ids = [];
    for (const value of savedIds) {
      const id = typeof value === 'string' ? value.trim() : '';
      if (!id || seen.has(id) || !available.has(id)) continue;
      seen.add(id);
      ids.push(id);
    }
    return ids;
  }

  function rows(providers, savedIds) {
    const list = providerList(providers);
    const byId = new Map(list.map((provider) => [provider.id, provider]));
    const ids = selected(list, savedIds);
    const selectedSet = new Set(ids);
    return [
      ...ids.map((id, index) => ({ ...byId.get(id), selected: true, order: index + 1 })),
      ...list.filter((provider) => !selectedSet.has(provider.id))
        .map((provider) => ({ ...provider, selected: false, order: null })),
    ];
  }

  function move(providers, savedIds, id, delta) {
    const ids = selected(providers, savedIds);
    const from = ids.indexOf(id);
    if (from < 0) return ids;
    const to = Math.max(0, Math.min(ids.length - 1, from + (delta < 0 ? -1 : 1)));
    if (from === to) return ids;
    [ids[from], ids[to]] = [ids[to], ids[from]];
    return ids;
  }

  function toggle(providers, savedIds, id, checked) {
    const ids = selected(providers, savedIds);
    const available = new Set(providerList(providers).map((provider) => provider.id));
    if (!available.has(id)) return ids;
    if (checked) {
      if (!ids.includes(id)) ids.push(id);
      return ids;
    }
    if (ids.length <= 1) return ids;
    return ids.filter((selectedId) => selectedId !== id);
  }

  function all(providers) {
    return providerList(providers).map((provider) => provider.id);
  }

  root.ProviderOrder = Object.freeze({ all, move, rows, selected, toggle });
})(typeof globalThis !== 'undefined' ? globalThis : window);
