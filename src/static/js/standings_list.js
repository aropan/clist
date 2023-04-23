function set_toggle_contest_groups() {
    $('#standings_list .contest .toggle').click(function() {
        var selector = $(this).attr('data-group')
        $(selector).slideToggle(200, 'linear').css('display', 'table-row');
        $('[data-group="' + selector +  '"] i').toggleClass('fa-caret-up').toggleClass('fa-caret-down')
        event.preventDefault()
    }).removeClass('toggle')
}

$(set_toggle_contest_groups)
