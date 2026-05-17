/* JavaScript for Vertical Student View. */

/* global Set:false */ // false means do not assign to Set

// The vertical marks blocks complete if they are completable by viewing.  The
// global variable SEEN_COMPLETABLES tracks blocks between separate loads of
// the same vertical (when a learner goes from one tab to the next, and then
// navigates back within a given sequential) to protect against duplicate calls
// to the server.

import BookmarkButton from 'course_bookmarks/js/views/bookmark_button';
import {markBlocksCompletedOnViewIfNeeded} from '../../../../../lms/static/completion/js/CompletionOnViewService.js';

var SEEN_COMPLETABLES = new Set();

function initExamProgressFooter($element) {
    var $footer = $element.find('.exam-progress-footer');
    if ($footer.length === 0) {
        return;
    }

    var mcTotal = parseInt($footer.data('mc-total'), 10);
    var $mcText = $footer.find('.exam-progress-mc');

    function recountSubmitted() {
        var submitted = 0;
        $element.find('.problems-wrapper').each(function() {
            if (parseInt($(this).data('attempts-used'), 10) > 0) {
                submitted++;
            }
        });
        $mcText.text('Multiple choice questions on this page: ' + submitted + ' of ' + mcTotal + ' submitted');
    }

    $element.on('progressChanged', '.problems-wrapper', function() {
        recountSubmitted();
    });
}

window.VerticalStudentView = function(runtime, element) {
    'use strict';
    var $element = $(element);
    var $bookmarkButtonElement = $element.find('.bookmark-button');
    markBlocksCompletedOnViewIfNeeded(runtime, element);
    initExamProgressFooter($element);
    return new BookmarkButton({
        el: $bookmarkButtonElement,
        bookmarkId: $bookmarkButtonElement.data('bookmarkId'),
        usageId: $element.data('usageId'),
        bookmarked: $element.parent('#seq_content').data('bookmarked'),
        apiUrl: $bookmarkButtonElement.data('bookmarksApiUrl')
    });
};
