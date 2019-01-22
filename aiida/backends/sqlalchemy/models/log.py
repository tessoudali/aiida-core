# -*- coding: utf-8 -*-
###########################################################################
# Copyright (c), The AiiDA team. All rights reserved.                     #
# This file is part of the AiiDA code.                                    #
#                                                                         #
# The code is hosted on GitHub at https://github.com/aiidateam/aiida_core #
# For further information on the license, see the LICENSE.txt file        #
# For further information please visit http://www.aiida.net               #
###########################################################################

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
from sqlalchemy.schema import Column
from sqlalchemy.types import Integer, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, backref
from sqlalchemy import ForeignKey

from aiida.common import timezone
from aiida.backends.sqlalchemy.models.base import Base
from aiida.common.exceptions import ValidationError

from sqlalchemy.dialects.postgresql import UUID

from .utils import uuid_func


class DbLog(Base):
    __tablename__ = "db_dblog"

    id = Column(Integer, primary_key=True)

    uuid = Column(UUID(as_uuid=True), default=uuid_func, unique=True)

    time = Column(DateTime(timezone=True), default=timezone.now)
    loggername = Column(String(255), index=True)
    levelname = Column(String(255), index=True)

    dbnode_id = Column(
        Integer,
        ForeignKey('db_dbnode.id', deferrable=True, initially="DEFERRED", ondelete="CASCADE"),
        nullable=False
    )

    message = Column(Text(), nullable=True)
    _metadata = Column('metadata', JSONB)

    ######### RELATIONSSHIP #########
    dbnode = relationship(
        'DbNode',
        backref=backref('dblogs', passive_deletes='all', cascade='merge')
    )

    def __init__(self, time, uuid=None, loggername="", levelname="", dbnode_id=None,
                 message=None, metadata=None):

        if not loggername or not levelname:
            raise ValidationError(
                "The loggername and levelname can't be empty")

        self.uuid = uuid
        self.time = time
        self.loggername = loggername
        self.levelname = levelname
        self.dbnode_id = dbnode_id
        self.message = message
        self._metadata = metadata or {}

    def __str__(self):
        return 'DbLog: {} for node {}: {}'.format(self.levelname, self.dbnode.id, self.message)
