# Author: Nic Wolfe <nic@wolfeden.ca>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of SickGear.
#
# SickGear is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SickGear is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SickGear.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import with_statement

import datetime
import threading

import sickbeard

from sickbeard import db, scheduler, helpers
from sickbeard import search_queue
from sickbeard import logger
from sickbeard import ui
from sickbeard import common
from sickbeard.search import wantedEpisodes


class BacklogSearchScheduler(scheduler.Scheduler):
    def forceSearch(self):
        self.action._set_lastBacklog(1)
        self.lastRun = datetime.datetime.fromordinal(1)

    def nextRun(self):
        if self.action._lastBacklog <= 1:
            return datetime.date.today()
        elif (self.action._lastBacklog + self.action.cycleTime) < datetime.date.today().toordinal():
            return datetime.date.today()
        else:
            return datetime.date.fromordinal(self.action._lastBacklog + self.action.cycleTime)


class BacklogSearcher:
    def __init__(self):

        self._lastBacklog = self._get_lastBacklog()
        self.cycleTime = sickbeard.BACKLOG_FREQUENCY
        self.lock = threading.Lock()
        self.amActive = False
        self.amPaused = False
        self.amWaiting = False

        self._resetPI()

    def _resetPI(self):
        self.percentDone = 0
        self.currentSearchInfo = {'title': 'Initializing'}

    def getProgressIndicator(self):
        if self.amActive:
            return ui.ProgressIndicator(self.percentDone, self.currentSearchInfo)
        else:
            return None

    def am_running(self):
        logger.log(u"amWaiting: " + str(self.amWaiting) + ", amActive: " + str(self.amActive), logger.DEBUG)
        return (not self.amWaiting) and self.amActive

    def searchBacklog(self, which_shows=None):

        if self.amActive:
            logger.log(u"Backlog is still running, not starting it again", logger.DEBUG)
            return

        if which_shows:
            show_list = which_shows
            standard_backlog = False
        else:
            show_list = sickbeard.showList
            standard_backlog = True

        self._get_lastBacklog()

        curDate = datetime.date.today().toordinal()
        fromDate = datetime.date.fromordinal(1)

        if not which_shows and not curDate - self._lastBacklog >= self.cycleTime:
            logger.log(u'Running limited backlog for episodes missed during the last %s day(s)' % str(sickbeard.BACKLOG_DAYS))
            fromDate = datetime.date.today() - datetime.timedelta(days=sickbeard.BACKLOG_DAYS)

        self.amActive = True
        self.amPaused = False

        # go through non air-by-date shows and see if they need any episodes
        for curShow in show_list:

            if curShow.paused:
                continue

            segments = wantedEpisodes(curShow, fromDate, make_dict=True)

            for season, segment in segments.items():
                self.currentSearchInfo = {'title': curShow.name + " Season " + str(season)}

                backlog_queue_item = search_queue.BacklogQueueItem(curShow, segment, standard_backlog=standard_backlog)
                sickbeard.searchQueueScheduler.action.add_item(backlog_queue_item)  # @UndefinedVariable
            else:
                logger.log(u'Nothing needs to be downloaded for %s, skipping' % str(curShow.name), logger.DEBUG)

        # don't consider this an actual backlog search if we only did recent eps
        # or if we only did certain shows
        if fromDate == datetime.date.fromordinal(1) and not which_shows:
            self._set_lastBacklog(curDate)

        self.amActive = False
        self._resetPI()

    def _get_lastBacklog(self):

        logger.log(u"Retrieving the last check time from the DB", logger.DEBUG)

        myDB = db.DBConnection()
        sqlResults = myDB.select("SELECT * FROM info")

        if len(sqlResults) == 0:
            lastBacklog = 1
        elif sqlResults[0]["last_backlog"] == None or sqlResults[0]["last_backlog"] == "":
            lastBacklog = 1
        else:
            lastBacklog = int(sqlResults[0]["last_backlog"])
            if lastBacklog > datetime.date.today().toordinal():
                lastBacklog = 1

        self._lastBacklog = lastBacklog
        return self._lastBacklog

    def _set_lastBacklog(self, when):

        logger.log(u"Setting the last backlog in the DB to " + str(when), logger.DEBUG)

        myDB = db.DBConnection()
        sqlResults = myDB.select("SELECT * FROM info")

        if len(sqlResults) == 0:
            myDB.action("INSERT INTO info (last_backlog, last_indexer) VALUES (?,?)", [str(when), 0])
        else:
            myDB.action("UPDATE info SET last_backlog=" + str(when))

    def run(self):
        try:
            self.searchBacklog()
        except:
            self.amActive = False
            raise
