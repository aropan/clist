function toggle_hide_contest(e) {
    e.preventDefault();
    var icon = $(this);
    $.ajax({
        type: 'GET',
        url: document.URL,
        data: {
            pk: icon.attr("data-contest-id"),
            action: "hide-contest-toggle",
        },
        success: function(data) {
            if (data != "created" && data != "deleted") {
                return;
            }
            icons = $('.hide-contest[data-contest-id="' + icon.attr("data-contest-id") + '"]');
            if (icon.hasClass("fa-eye") ^ (data == "deleted")) {
                if (icon.hasClass("fa-eye")) {
                    icons.parent().find('.contest_title>a').css({textDecoration: 'line-through'});
                    icons.parent().find('.fc-title').css({textDecoration: 'line-through'});
                } else {
                    icons.parent().find('.contest_title>a').css({textDecoration: 'none'});
                    icons.parent().find('.fc-title').css({textDecoration: 'none'});
                }
                icons.toggleClass("fa-eye");
                icons.toggleClass("fa-eye-slash");
            }
        },
    })
}

function toggle_party_contest(e) {
    e.preventDefault();
    var icon = $(this);
    $.ajax({
        type: 'GET',
        url: document.URL,
        data: {
            pk: icon.attr("data-contest-id"),
            action: "party-contest-toggle",
        },
        success: function(data) {
            if (data != "created" && data != "deleted") {
                return;
            }
            var id = parseInt(icon.attr("data-contest-id"));
            if (party_contests_set.has(id) ^ (data == "created")) {
                if (party_contests_set.has(id)) {
                    party_contests_set.delete(id)
                } else {
                    party_contests_set.add(id)
                }

                $(".party-check[data-contest-id='" + id + "']").toggleClass("fa-check-square");
                $(".party-check[data-contest-id='" + id + "']").toggleClass("fa-square");
            }
        },
    })
}

$(function() {
    $(".toggle").click(function(e) {
        var cls = $(this).attr("data-group");
        $(cls).slideToggle(200, "linear");
        var icon = $(".badge[data-group='{0}']".format(cls)).find("i");
        icon.toggleClass("fa-caret-down");
        icon.toggleClass("fa-caret-up");
        e.preventDefault();
    })

    $("#toggle-all").click(function (e) {
        var icon = $(this).find("i");
        var cls = $(icon).attr("class").match(/fa-caret-[\w-]*/)[0];
        icon.toggleClass("fa-caret-down");
        icon.toggleClass("fa-caret-up");
        $(".toggle.badge>i[class~='{0}']".format(cls)).click();
        e.preventDefault();
    })

    $(".party-check.has-permission-toggle-party-contest[data-contest-id]").click(toggle_party_contest)
    $(".hide-contest[data-contest-id]").click(toggle_hide_contest)
});
