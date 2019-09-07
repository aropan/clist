$(function() {
    filterTimeoutUpdate = 500

    $('[rel=tooltip]').tooltip({
        placement: 'top',
    })
    var timeoutId = null
    var filterInput = $('#filter input')
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
            filterCallbackList(value)
            filterCallbackCalendar(value)
        }, filterTimeoutUpdate);
    })

    if (filterInput.val()) {
        filterInput.keyup()
    }

    $('#toggle-view').change(function() {
        var target = $(this).prop('checked')? '#list-view' : '#calendar-view'
        $('.list-calendar-views .active').toggleClass('active')
        $(target).toggleClass('active')
        $(window).resize()  // to collapse list day events in calendar
    })
})
