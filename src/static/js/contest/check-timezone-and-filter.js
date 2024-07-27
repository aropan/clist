$(function() {
    filterTimeoutUpdate = 500

    $('[rel=tooltip]').tooltip({
        placement: 'top',
    })
    var timeoutId = null
    var filterInput = $('#filter #search')
    filterInput.keyup(function(e) {
        if (e.which == 27) {
            $(this).val('')
        }
        var value = $(this).val()
        $('#filter .input-group-addon.icon .fa-search')
            .removeClass('fa-search')
            .addClass('fa-spinner')
            .addClass('fa-pulse')
        if (timeoutId != null) {
            clearTimeout(timeoutId)
        }
        timeoutId = setTimeout(function() {
            $('#filter .input-group-addon.icon').html('<i class="fa fa-search"></i>')
            filterCallbackList()
            filterCallbackCalendar()
        }, filterTimeoutUpdate);
    })

    var favorite_button_active = $('#filter button[name="favorite"].active')
    if (filterInput.val() || favorite_button_active.length) {
        filterInput.keyup()
    }

    $('#toggle-view').change(function() {
        var target_view = $(this).prop('checked')? 'list' : 'calendar'
        $('.list-calendar-views .active').toggleClass('active')
        $('#' + target_view + '-view').toggleClass('active')

        // to collapse list day events in calendar
        $(window).resize()
        calendar.render()

        update_urls_params({'view': target_view})
    })

    var fav_buttons = $('#filter button[name="favorite"]')
    fav_buttons.click(function() {
        var btn = $(this)
        var active = btn.hasClass('active')
        fav_buttons.removeClass('active')
        if (!active) {
            btn.addClass('active')
        }
        filterCallbackList()
        filterCallbackCalendar()
        return false
    })
})
