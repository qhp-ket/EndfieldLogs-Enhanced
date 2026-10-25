// Content widths have a readable floor; extra columns grow the native window.
(() => {
  let signature = '', sentSignature = '', channel, pendingReference, pendingFit = false;
  let latestArgs, measuredDpr;
  const root = document.documentElement;
  const canvas = document.createElement('canvas'), context = canvas.getContext('2d'), fonts = new Map();
  function textWidth(node, text = node?.textContent || '') {
    if (!node) return 0;
    let font = fonts.get(node.className);
    if (!font) {
      const style = getComputedStyle(node);
      const scale = Number(getComputedStyle(root).getPropertyValue('--overlay-font-scale')) || 1;
      font = {value:`${style.fontStyle} ${style.fontWeight} ${parseFloat(style.fontSize)/scale}px ${style.fontFamily}`,
              spacing:(parseFloat(style.letterSpacing) || 0)/scale};
      fonts.set(node.className, font);
    }
    context.font = font.value;
    return context.measureText(text).width + Math.max(0, text.length-1)*font.spacing;
  }
  const bucket = width => Math.ceil(width/8)*8;
  const tracks = widths => widths.map(width => `calc(${width}px * var(--overlay-window-scale, 1))`).join(' ');
  function publish(reference, canFit, reset) {
    if (pendingReference !== reference) window.endfieldOverlay?.setContentReference(reference);
    pendingReference = reference;
    pendingFit = canFit;
    if (channel && canFit && (signature !== sentSignature || reset)) {
      channel.fit(reference.width, reference.height);
      sentSignature = signature;
    }
  }
  if (window.qt?.webChannelTransport && window.QWebChannel) {
    new QWebChannel(qt.webChannelTransport, bridge => {
      channel = bridge.objects.damageContent;
      if (pendingReference && pendingFit) {
        channel.fit(pendingReference.width, pendingReference.height);
        sentSignature = signature;
      }
    });
  }
  window.fitDamageTable = (columns, records, barMode, hasSnapshot) => {
    latestArgs = [columns, records, barMode, hasSnapshot];
    const shell = document.querySelector('.overlay-shell'), card = document.querySelector('.overlay-card');
    if (!shell || !card) return;
    const headers = document.getElementById('columnsHead').children;
    const config = window.endfieldOverlay?.config || {};
    const canFit = !!window.endfieldOverlay?.config && (!config.waitForSnapshot || hasSnapshot);
    const reset = !!config.fitReset;
    delete config.fitReset;
    const fontScale = Math.max(.5, Math.min(3, Number(config.fontScale) || 1));
    const avatarScale = Number(getComputedStyle(root).getPropertyValue('--avatar-scale')) || 1;
    const avatarWidth = config.settings?.show_character_avatars !== 'off' ? 32*avatarScale+6 : 0;
    const nameProbe = records.length ? null : Object.assign(document.createElement('span'), {className:'player-name'});
    if (nameProbe) { nameProbe.style.position='absolute'; nameProbe.style.visibility='hidden'; card.append(nameProbe); }
    const exemplar = records[0]?.nameNode || nameProbe;
    const names = Math.max(textWidth(exemplar, '角色名称'),
      ...records.map(record => Math.max(textWidth(record.nameNode), textWidth(record.meta))));
    const identityWidth = bucket(Math.max(textWidth(headers[0])*fontScale,
      (names+13)*fontScale+avatarWidth));
    if (nameProbe) nameProbe.remove();
    const widths = columns.map((column, index) => {
      const cell = records[0]?.cells.get(column.key);
      // Before the first snapshot use the same numeric cell font as the rows.
      const probe = cell || Object.assign(document.createElement('span'), {className:`row-stat ${column.className}`});
      if (!cell) { probe.style.position='absolute'; probe.style.visibility='hidden'; card.append(probe); }
      const floor = textWidth(probe, column.key.endsWith('_rate') ? '100.0%' : '100.00M');
      const width = bucket((Math.max(floor, textWidth(headers[index+1]),
        ...records.map(record => textWidth(record.cells.get(column.key))))+16)*fontScale);
      if (!cell) probe.remove();
      return width;
    });
    const liveTracks = tracks([identityWidth, ...widths]);
    root.style.setProperty('--table-columns', liveTracks);
    const metrics = [...document.querySelectorAll('.header-metric')];
    const metricWidth = metrics.reduce((sum, node) => sum+Math.max(textWidth(node.children[0]), textWidth(node.children[1])), 0);
    const headerWidth = (metricWidth + Math.max(0, metrics.length-1)*24
      + textWidth(document.getElementById('combatTime')) + 8+12+12+42+16)*fontScale;
    const width = Math.max(320, bucket(identityWidth+widths.reduce((sum, value) => sum+value, 0)
      +(columns.length*6+32)*fontScale+4), bucket(headerWidth));
    const next = JSON.stringify([width, liveTracks, records.length, avatarScale, fontScale, barMode, devicePixelRatio]);
    if (next === signature) {
      publish(pendingReference, canFit, reset);
      return;
    }
    signature = next;
    const changes = [
      [root, '--overlay-window-scale', '1'],
      [root, '--overlay-font-scale', String(fontScale)],
      [shell, 'width', `${width}px`], [shell, 'max-height', 'none'], [card, 'max-height', 'none'],
    ];
    const previous = changes.map(([node, key]) => [node.style.getPropertyValue(key), node.style.getPropertyPriority(key)]);
    let height;
    try {
      for (const [node, key, value] of changes) node.style.setProperty(key, value);
      height = shell.getBoundingClientRect().height;
      measuredDpr = devicePixelRatio;
    } finally {
      changes.forEach(([node, key], index) => {
        const [value, priority] = previous[index];
        if (value) node.style.setProperty(key, value, priority);
        else node.style.removeProperty(key);
      });
    }
    publish({width, height}, canFit, reset);
  };
  // Chromium may start at the system DPI before its native window is placed.
  // An empty table has no subsequent row update to invalidate that first fit.
  window.addEventListener('resize', () => {
    if (latestArgs && !latestArgs[1].length && measuredDpr !== devicePixelRatio)
      requestAnimationFrame(() => window.fitDamageTable(...latestArgs));
  });
})();
