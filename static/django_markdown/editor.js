jQuery(function ($) {
    $('script.markItUpEditorConfig').each(function (i, config_element) {
        var config = JSON.parse(config_element.textContent);
        $(config["selector"]).each(function (k, el) {
            var el = $(el);
            if(!el.hasClass("markItUpEditor")) {
                el.markItUp(mySettings, config["extra_settings"]);
            }
        });
    });
});
