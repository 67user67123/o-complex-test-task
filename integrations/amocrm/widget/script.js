define(['jquery'], function ($) {
  'use strict';

  return function () {
    var self = this;
    var rootClass = 'local-manager-assistant-v1';

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, function (char) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char];
      });
    }

    function serviceUrl() {
      try {
        var value = String(self.get_settings().service_url || '').trim();
        var url = new URL(value);
        // No secrets or conversation data may be put into a navigation URL.
        if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || url.search || url.hash) {
          return null;
        }
        return url.href;
      } catch (error) {
        return null;
      }
    }

    this.callbacks = {
      render: function () {
        if (self.system().area !== 'lcard') {
          return true;
        }

        var lang = self.i18n('ui');
        var url = serviceUrl();
        var content = '<div class="' + rootClass + '">' +
          '<p class="' + rootClass + '__intro">' + escapeHtml(lang.intro) + '</p>' +
          '<p>' + escapeHtml(lang.steps) + '</p>';

        if (url) {
          content += '<details class="' + rootClass + '__embedded">' +
            '<summary>' + escapeHtml(lang.open_inline) + '</summary>' +
            '<iframe class="' + rootClass + '__frame" src="' + escapeHtml(url) +
            '" title="' + escapeHtml(lang.frame_title) + '" loading="lazy" ' +
            'referrerpolicy="no-referrer" allow="clipboard-write" ' +
            'sandbox="allow-scripts allow-same-origin allow-forms"></iframe></details>' +
            '<a class="' + rootClass + '__open" href="' + escapeHtml(url) +
            '" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">' +
            escapeHtml(lang.open) + '</a>' +
            '<p class="' + rootClass + '__note">' + escapeHtml(lang.new_tab) + '</p>';
        } else {
          content += '<p class="' + rootClass + '__error" role="alert">' +
            escapeHtml(lang.invalid_url) + '</p>';
        }

        content += '</div>';
        self.render_template({
          caption: { class_name: rootClass + '__caption' },
          body: '<link rel="stylesheet" type="text/css" href="' +
            escapeHtml(self.params.path + '/style.css?v=' + self.get_version()) + '">' + content,
          render: ''
        });
        return true;
      },

      init: function () { return true; },
      // A normal anchor works with keyboard navigation and needs no global listener.
      bind_actions: function () { return true; },
      destroy: function () { return true; },

      settings: function ($settingsBody) {
        if ($settingsBody && $settingsBody.length) {
          $settingsBody.find('.' + rootClass + '__settings').remove();
          $('<p>').addClass(rootClass + '__settings')
            .text(self.i18n('ui').settings_help).appendTo($settingsBody);
        }
        return true;
      },

      // amoCRM saves the manifest's settings; no external API request is needed.
      onSave: function () { return true; }
    };

    return this;
  };
});
