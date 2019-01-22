# -*- coding: utf-8 -*-
###########################################################################
# Copyright (c), The AiiDA team. All rights reserved.                     #
# This file is part of the AiiDA code.                                    #
#                                                                         #
# The code is hosted on GitHub at https://github.com/aiidateam/aiida_core #
# For further information on the license, see the LICENSE.txt file        #
# For further information please visit http://www.aiida.net               #
###########################################################################
"""
Tests for the migration engine (Alembic) as well as for the AiiDA migrations
for SQLAlchemy.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import unittest
from contextlib import contextmanager

import os
from alembic import command
from alembic.config import Config
from six.moves import zip

from aiida.backends import sqlalchemy as sa
from aiida.backends.sqlalchemy import utils
from aiida.backends.sqlalchemy.models.base import Base
from aiida.backends.sqlalchemy.tests.utils import new_database
from aiida.backends.testbase import AiidaTestCase


class TestMigrationsSQLA(AiidaTestCase):
    """
    This class contains tests for the migration mechanism of SQLAlchemy called
    alembic. It checks if the migrations can be applied and removed correctly.
    """
    # The path to the folder that contains the migration configuration (the
    # actual configuration - not the testing)
    migr_method_dir_path = None
    # The path of the migration configuration (the actual configuration - not
    # the testing)
    alembic_dpath = None

    migrate_from = None
    migrate_to = None

    @classmethod
    def setUpClass(cls, *args, **kwargs):
        """
        Prepare the test class with the alembivc configuration
        """
        super(TestMigrationsSQLA, cls).setUpClass(*args, **kwargs)
        cls.migr_method_dir_path = os.path.dirname(os.path.realpath(utils.__file__))
        alembic_dpath = os.path.join(cls.migr_method_dir_path, utils.ALEMBIC_REL_PATH)
        cls.alembic_cfg = Config()
        cls.alembic_cfg.set_main_option('script_location', alembic_dpath)

    def setUp(self):
        """
        Go to the migrate_from revision, apply setUpBeforeMigration, then
        run the migration.
        """
        super(TestMigrationsSQLA, self).setUp()
        from aiida.orm import autogroup

        self.current_autogroup = autogroup.current_autogroup
        autogroup.current_autogroup = None
        assert self.migrate_from and self.migrate_to, \
            "TestCase '{}' must define migrate_from and migrate_to properties".format(type(self).__name__)

        try:
            self.migrate_db_down(self.migrate_from)
            self.setUpBeforeMigration()
            self.migrate_db_up(self.migrate_to)
        except Exception:
            # Bring back the DB to the correct state if this setup part fails
            self._reset_database_and_schema()
            raise

    def migrate_db_up(self, destination):
        """
        Perform a migration upwards (upgrade) with alembic

        :param destination: the name of the destination migration
        """
        # Undo all previous real migration of the database
        with sa.engine.connect() as connection:
            self.alembic_cfg.attributes['connection'] = connection  # pylint: disable=unsupported-assignment-operation
            command.upgrade(self.alembic_cfg, destination)

    def migrate_db_down(self, destination):
        """
        Perform a migration downwards (downgrade) with alembic

        :param destination: the name of the destination migration
        """
        with sa.engine.connect() as connection:
            self.alembic_cfg.attributes['connection'] = connection  # pylint: disable=unsupported-assignment-operation
            command.downgrade(self.alembic_cfg, destination)

    def tearDown(self):
        """
        Resets both the database content and the schema to prepare for the
        next test
        """
        from aiida.orm import autogroup
        self._reset_database_and_schema()
        autogroup.current_autogroup = self.current_autogroup
        super(TestMigrationsSQLA, self).tearDown()

    def setUpBeforeMigration(self):  # pylint: disable=invalid-name
        """
        Anything to do before running the migrations.
        This is typically implemented in test subclasses.
        """

    def _reset_database_and_schema(self):
        """
        Bring back the DB to the correct state.

        It is important to also reset the database content to avoid hanging
        of tests.
        """
        self.reset_database()
        self.migrate_db_up("head")

    @property
    def current_rev(self):
        """
        Utility method to get the current revision string
        """
        from alembic.migration import MigrationContext  # pylint: disable=import-error
        with sa.engine.begin() as connection:
            context = MigrationContext.configure(connection)
            current_rev = context.get_current_revision()
        return current_rev

    @staticmethod
    def get_auto_base():
        """
        Return the automap_base class that automatically inspects the current
        database and return SQLAlchemy Models.

        Note that these are NOT the ones in AiiDA SQLAlchemy models, so do not
        have the special methods that we define there (like .save()).
        """
        from alembic.migration import MigrationContext  # pylint: disable=import-error
        from sqlalchemy.ext.automap import automap_base  # pylint: disable=import-error,no-name-in-module

        with sa.engine.begin() as connection:
            context = MigrationContext.configure(connection)
            bind = context.bind

            base = automap_base()
            # reflect the tables
            base.prepare(bind.engine, reflect=True)

            return base

    @staticmethod
    @contextmanager
    def get_session():
        """
        Return a session that is properly closed after use.
        """
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        with sa.engine.begin() as connection:
            session = Session(connection.engine)
            yield session
            session.close()

    def get_current_table(self, table_name):
        """
        Return a Model instantiated at the correct migration.
        Note that this is obtained by inspecting the database and not
        by looking into the models file. So, special methods possibly defined
        in the models files/classes are not present.

        For instance, you can do::

          DbGroup = self.get_current_table('db_dbgroup')

        :param table_name: the name of the table.
        """
        base = self.get_auto_base()
        return getattr(base.classes, table_name)


class TestBackwardMigrationsSQLA(TestMigrationsSQLA):
    """
    This is the equivalent of TestMigrationsSQLA for backward migrations.
    It assumes that the migrate_from revision is higher in the hierarchy
    than the migrate_to revision.
    """

    def setUp(self):
        """
        Go to the migrate_from revision, apply setUpBeforeMigration, then
        run the migration.
        """
        AiidaTestCase.setUp(self)  # pylint: disable=bad-super-call
        from aiida.orm import autogroup

        self.current_autogroup = autogroup.current_autogroup
        autogroup.current_autogroup = None
        assert self.migrate_from and self.migrate_to, \
            "TestCase '{}' must define migrate_from and migrate_to properties".format(type(self).__name__)

        try:
            self.migrate_db_down(self.migrate_from)
            self.setUpBeforeMigration()
            self.migrate_db_down(self.migrate_to)
        except Exception:
            # Bring back the DB to the correct state if this setup part fails
            self._reset_database_and_schema()
            raise


class TestMigrationEngine(TestMigrationsSQLA):
    """
    Just a simple test to verify that the TestMigrationsSQLA class indeed
    works and moves between the expected migration revisions
    """
    migrate_from = 'b8b23ddefad4'  # b8b23ddefad4_dbgroup_name_to_label_type_to_type_string.py
    migrate_to = 'e72ad251bcdb'  # e72ad251bcdb_dbgroup_class_change_type_string_values.py

    def setUpBeforeMigration(self):
        """
        Cache the start revision
        """
        self.start_revision = self.current_rev

    def test_revision_numbers(self):
        """
        Check that we went to the correct version
        """
        self.assertEqual(self.start_revision, self.migrate_from)
        self.assertEqual(self.current_rev, self.migrate_to)


class TestGroupRenamingMigration(TestMigrationsSQLA):
    """
    Test the migration that renames the DbGroup type strings
    """
    # b8b23ddefad4_dbgroup_name_to_label_type_to_type_string.py
    # e72ad251bcdb_dbgroup_class_change_type_string_values.py
    migrate_from = 'b8b23ddefad4'  # b8b23ddefad4_dbgroup_name_to_label_type_to_type_string.py
    migrate_to = 'e72ad251bcdb'  # e72ad251bcdb_dbgroup_class_change_type_string_values.py

    def setUpBeforeMigration(self):
        """
        Create the DbGroups with the old type strings
        """
        # Create group
        DbGroup = self.get_current_table('db_dbgroup')  # pylint: disable=invalid-name
        DbUser = self.get_current_table('db_dbuser')  # pylint: disable=invalid-name

        with self.get_session() as session:
            default_user = DbUser(is_superuser=False, email="{}@aiida.net".format(self.id()))
            session.add(default_user)
            session.commit()

            # test user group type_string: '' -> 'user'
            group_user = DbGroup(label='test_user_group', user_id=default_user.id, type_string='')
            session.add(group_user)
            # test data.upf group type_string: 'data.upf.family' -> 'data.upf'
            group_data_upf = DbGroup(
                label='test_data_upf_group', user_id=default_user.id, type_string='data.upf.family')
            session.add(group_data_upf)
            # test auto.import group type_string: 'aiida.import' -> 'auto.import'
            group_autoimport = DbGroup(label='test_import_group', user_id=default_user.id, type_string='aiida.import')
            session.add(group_autoimport)
            # test auto.run group type_string: 'autogroup.run' -> 'auto.run'
            group_autorun = DbGroup(label='test_autorun_group', user_id=default_user.id, type_string='autogroup.run')
            session.add(group_autorun)

            session.commit()

            # Store values for later tests
            self.group_user_pk = group_user.id
            self.group_data_upf_pk = group_data_upf.id
            self.group_autoimport_pk = group_autoimport.id
            self.group_autorun_pk = group_autorun.id

    def test_group_string_update(self):
        """
        Test that the type strings are properly migrated
        """
        DbGroup = self.get_current_table('db_dbgroup')  # pylint: disable=invalid-name

        with self.get_session() as session:

            # test user group type_string: '' -> 'user'
            group_user = session.query(DbGroup).filter(DbGroup.id == self.group_user_pk).one()
            self.assertEqual(group_user.type_string, 'user')

            # test data.upf group type_string: 'data.upf.family' -> 'data.upf'
            group_data_upf = session.query(DbGroup).filter(DbGroup.id == self.group_data_upf_pk).one()
            self.assertEqual(group_data_upf.type_string, 'data.upf')

            # test auto.import group type_string: 'aiida.import' -> 'auto.import'
            group_autoimport = session.query(DbGroup).filter(DbGroup.id == self.group_autoimport_pk).one()
            self.assertEqual(group_autoimport.type_string, 'auto.import')

            # test auto.run group type_string: 'autogroup.run' -> 'auto.run'
            group_autorun = session.query(DbGroup).filter(DbGroup.id == self.group_autorun_pk).one()
            self.assertEqual(group_autorun.type_string, 'auto.run')


class TestMigrationSchemaVsModelsSchema(unittest.TestCase):
    """
    This class checks that the schema that results from a migration is the
    same generated by the models. This is important since migrations are
    frequently written by hand or extended manually and we have to ensure
    that the final result is what is conceived in the SQLA models.
    """
    # The path to the folder that contains the migration configuration (the
    # actual configuration - not the testing)
    migr_method_dir_path = None
    # The path of the migration configuration (the actual configuration - not
    # the testing)
    alembic_dpath = None
    # The alembic configuration needed for the migrations is stored here
    alembic_cfg_left = None

    # The URL of the databases
    db_url_left = None
    db_url_right = None

    def setUp(self):
        from sqlalchemydiff.util import get_temporary_uri
        from aiida.backends.sqlalchemy.migrations import versions

        self.migr_method_dir_path = os.path.dirname(os.path.realpath(utils.__file__))
        # Set the alembic script directory location
        self.alembic_dpath = os.path.join(self.migr_method_dir_path, utils.ALEMBIC_REL_PATH)

        # Constructing the versions directory
        versions_dpath = os.path.join(os.path.dirname(versions.__file__))

        # Setting dynamically the the path to the alembic configuration
        # (this is where the env.py file can be found)
        self.alembic_cfg_left = Config()
        self.alembic_cfg_left.set_main_option('script_location', self.alembic_dpath)
        # Setting dynamically the versions directory. These are the
        # migration scripts to pass from one version to the other. The
        # default ones are overridden with test-specific migrations.
        self.alembic_cfg_left.set_main_option('version_locations', versions_dpath)

        # The correction URL to the SQLA database of the current
        # AiiDA connection
        curr_db_url = sa.engine.url

        # Create new urls for the two new databases
        self.db_url_left = get_temporary_uri(str(curr_db_url))
        self.db_url_right = get_temporary_uri(str(curr_db_url))

        # Put the correct database url to the database used by alembic
        self.alembic_cfg_left.set_main_option("sqlalchemy.url", self.db_url_left)

        # Database creation
        new_database(self.db_url_left)
        new_database(self.db_url_right)

    def tearDown(self):
        from sqlalchemydiff.util import destroy_database
        destroy_database(self.db_url_left)
        destroy_database(self.db_url_right)

    def test_model_and_migration_schemas_are_the_same(self):  # pylint: disable=invalid-name
        """Compare two databases.

        Compares the database obtained with all migrations against the
        one we get out of the models.  It produces a text file with the
        results to help debug differences.
        """
        from sqlalchemy.engine import create_engine  # pylint: disable=import-error,no-name-in-module
        from sqlalchemydiff import compare

        with create_engine(self.db_url_left).begin() as connection:
            self.alembic_cfg_left.attributes['connection'] = connection  # pylint: disable=unsupported-assignment-operation
            command.upgrade(self.alembic_cfg_left, "head")

        engine_right = create_engine(self.db_url_right)
        Base.metadata.create_all(engine_right)
        engine_right.dispose()

        result = compare(self.db_url_left, self.db_url_right, set(['alembic_version']))

        self.assertTrue(result.is_match, "The migration database doesn't match to the one "
                        "created by the models.\nDifferences: " + result._dump_data(result.errors))  # pylint: disable=protected-access


class TestCalcAttributeKeysMigration(TestMigrationsSQLA):
    """Test the migration of the keys of certain attribute for ProcessNodes and CalcJobNodes."""

    migrate_from = 'e72ad251bcdb'  # e72ad251bcdb_dbgroup_class_change_type_string_values
    migrate_to = '7ca08c391c49'  # 7ca08c391c49_calc_job_option_attribute_keys

    KEY_RESOURCES_OLD = 'jobresource_params'
    KEY_RESOURCES_NEW = 'resources'
    KEY_PARSER_NAME_OLD = 'parser'
    KEY_PARSER_NAME_NEW = 'parser_name'
    KEY_PROCESS_LABEL_OLD = '_process_label'
    KEY_PROCESS_LABEL_NEW = 'process_label'
    KEY_ENVIRONMENT_VARIABLES_OLD = 'custom_environment_variables'
    KEY_ENVIRONMENT_VARIABLES_NEW = 'environment_variables'

    def setUpBeforeMigration(self):
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        DbNode = self.get_auto_base().classes.db_dbnode  # pylint: disable=invalid-name
        DbUser = self.get_auto_base().classes.db_dbuser  # pylint: disable=invalid-name

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)

                user = DbUser(is_superuser=False, email="{}@aiida.net".format(self.id()))
                session.add(user)
                session.commit()

                self.resources = {'number_machines': 1}
                self.parser_name = 'aiida.parsers:parser'
                self.process_label = 'TestLabel'
                self.environment_variables = {}

                attributes = {
                    self.KEY_RESOURCES_OLD: self.resources,
                    self.KEY_PARSER_NAME_OLD: self.parser_name,
                    self.KEY_PROCESS_LABEL_OLD: self.process_label,
                    self.KEY_ENVIRONMENT_VARIABLES_OLD: self.environment_variables,
                }
                node_work = DbNode(type='node.process.workflow.WorkflowNode.', attributes=attributes, user_id=user.id)
                node_calc = DbNode(
                    type='node.process.calculation.calcjob.CalcJobNode.', attributes=attributes, user_id=user.id)

                session.add(node_work)
                session.add(node_calc)
                session.commit()

                self.node_work_id = node_work.id
                self.node_calc_id = node_calc.id
            finally:
                session.close()

    def test_attribute_key_changes(self):
        """Verify that the keys are successfully changed of the affected attributes."""
        import ast
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        DbNode = self.get_auto_base().classes.db_dbnode  # pylint: disable=invalid-name

        not_found = tuple([0])

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)

                node_work = session.query(DbNode).filter(DbNode.id == self.node_work_id).one()
                self.assertEqual(node_work.attributes.get(self.KEY_PROCESS_LABEL_NEW), self.process_label)
                self.assertEqual(node_work.attributes.get(self.KEY_PROCESS_LABEL_OLD, not_found), not_found)

                node_calc = session.query(DbNode).filter(DbNode.id == self.node_calc_id).one()

                # The dictionaries need to be cast with ast.literal_eval, because the `get` will return a string
                # representation of the dictionary that the attribute contains
                self.assertEqual(node_calc.attributes.get(self.KEY_PROCESS_LABEL_NEW), self.process_label)
                self.assertEqual(node_calc.attributes.get(self.KEY_PARSER_NAME_NEW), self.parser_name)
                self.assertEqual(ast.literal_eval(node_calc.attributes.get(self.KEY_RESOURCES_NEW)), self.resources)
                self.assertEqual(
                    ast.literal_eval(node_calc.attributes.get(self.KEY_ENVIRONMENT_VARIABLES_NEW)),
                    self.environment_variables)
                self.assertEqual(node_calc.attributes.get(self.KEY_PROCESS_LABEL_OLD, not_found), not_found)
                self.assertEqual(node_calc.attributes.get(self.KEY_PARSER_NAME_OLD, not_found), not_found)
                self.assertEqual(node_calc.attributes.get(self.KEY_RESOURCES_OLD, not_found), not_found)
                self.assertEqual(node_calc.attributes.get(self.KEY_ENVIRONMENT_VARIABLES_OLD, not_found), not_found)
            finally:
                session.close()


class TestDbLogMigrationRecordCleaning(TestMigrationsSQLA):
    """Test the migration of the keys of certain attribute for ProcessNodes and CalcJobNodes."""

    migrate_from = '7ca08c391c49'  # e72ad251bcdb_dbgroup_class_change_type_string_values
    migrate_to = '041a79fc615f'  # 041a79fc615f_dblog_cleaning

    def setUpBeforeMigration(self):
        # pylint: disable=too-many-locals,too-many-statements
        import importlib
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module
        from aiida.backends.sqlalchemy.utils import dumps_json

        log_migration = importlib.import_module(
            'aiida.backends.sqlalchemy.migrations.versions.041a79fc615f_dblog_cleaning')

        DbUser = self.get_auto_base().classes.db_dbuser  # pylint: disable=invalid-name
        DbNode = self.get_auto_base().classes.db_dbnode  # pylint: disable=invalid-name
        DbWorkflow = self.get_auto_base().classes.db_dbworkflow  # pylint: disable=invalid-name
        DbLog = self.get_auto_base().classes.db_dblog  # pylint: disable=invalid-name

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)

                user = DbUser(is_superuser=False, email="{}@aiida.net".format(self.id()))
                session.add(user)
                session.commit()

                calc_1 = DbNode(type="node.process.calculation.CalculationNode.", user_id=user.id)
                param = DbNode(type="data.parameter.ParameterData.", user_id=user.id)
                leg_workf = DbWorkflow(label="Legacy WorkflowNode", user_id=user.id)
                calc_2 = DbNode(type="node.process.calculation.CalculationNode.", user_id=user.id)

                session.add(calc_1)
                session.add(param)
                session.add(leg_workf)
                session.add(calc_2)
                session.commit()

                log_1 = DbLog(
                    loggername='CalculationNode logger',
                    objpk=calc_1.id,
                    objname='node.calculation.job.quantumespresso.pw.',
                    message='calculation node 1',
                    metadata={
                        "msecs": 719.0849781036377,
                        "objpk": calc_1.id,
                        "lineno": 350,
                        "thread": 140011612940032,
                        "asctime": "10/21/2018 12:39:51 PM",
                        "created": 1540118391.719085,
                        "levelno": 23,
                        "message": "calculation node 1",
                        "objname": "node.calculation.job.quantumespresso.pw.",
                    })
                log_2 = DbLog(
                    loggername='something.else logger',
                    objpk=param.id,
                    objname='something.else.',
                    message='parameter data with log message')
                log_3 = DbLog(
                    loggername='TopologicalWorkflow logger',
                    objpk=leg_workf.id,
                    objname='aiida.workflows.user.topologicalworkflows.topo.TopologicalWorkflow',
                    message='parameter data with log message')
                log_4 = DbLog(
                    loggername='CalculationNode logger',
                    objpk=calc_2.id,
                    objname='node.calculation.job.quantumespresso.pw.',
                    message='calculation node 2',
                    metadata={
                        "msecs": 719.0849781036377,
                        "objpk": calc_2.id,
                        "lineno": 360,
                        "levelno": 23,
                        "message": "calculation node 1",
                        "objname": "node.calculation.job.quantumespresso.pw.",
                    })

                session.add(log_1)
                session.add(log_2)
                session.add(log_3)
                session.add(log_4)

                session.commit()

                # Storing temporarily information needed for the check at the test
                self.to_check = dict()

                # Keeping calculation & calculation log ids
                self.to_check['CalculationNode'] = (
                    calc_1.id,
                    log_1.id,
                    calc_2.id,
                    log_4.id,
                )

                # The columns to project
                cols_to_project = []
                for val in log_migration.values_to_export:
                    cols_to_project.append(getattr(DbLog, val))

                # Getting the serialized ParameterData logs
                param_data = session.query(DbLog).filter(DbLog.objpk == param.id).filter(
                    DbLog.objname == 'something.else.').with_entities(*cols_to_project).one()
                serialized_param_data = dumps_json([(dict(list(zip(param_data.keys(), param_data))))])
                # Getting the serialized logs for the unknown entity logs (as the export migration fuction
                # provides them) - this should coincide to the above
                serialized_unknown_exp_logs = log_migration.get_serialized_unknown_entity_logs(connection)
                # Getting their number
                unknown_exp_logs_no = log_migration.get_unknown_entity_log_no(connection)
                self.to_check['ParameterData'] = (serialized_param_data, serialized_unknown_exp_logs,
                                                  unknown_exp_logs_no)

                # Getting the serialized legacy workflow logs
                leg_wf = session.query(DbLog).filter(DbLog.objpk == leg_workf.id).filter(
                    DbLog.objname == 'aiida.workflows.user.topologicalworkflows.topo.TopologicalWorkflow'
                ).with_entities(*cols_to_project).one()
                serialized_leg_wf_logs = dumps_json([(dict(list(zip(leg_wf.keys(), leg_wf))))])
                # Getting the serialized logs for the legacy workflow logs (as the export migration function
                # provides them) - this should coincide to the above
                serialized_leg_wf_exp_logs = log_migration.get_serialized_legacy_workflow_logs(connection)
                eg_wf_exp_logs_no = log_migration.get_legacy_workflow_log_no(connection)
                self.to_check['WorkflowNode'] = (serialized_leg_wf_logs, serialized_leg_wf_exp_logs, eg_wf_exp_logs_no)
            except:
                session.rollback()
                raise
            finally:
                session.close()

    def test_dblog_calculation_node(self):
        """
        Verify that after the migration there is only two log records left and verify that they corresponds to
        the CalculationNodes.
        """
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        DbLog = self.get_auto_base().classes.db_dblog  # pylint: disable=invalid-name

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)

                # Check that only two log records exist
                self.assertEqual(session.query(DbLog).count(), 2, "There should be two log records left")

                # Get the node id of the log record referencing the node and verify that it is the correct one
                dbnode_id_1 = session.query(DbLog).filter(
                    DbLog.id == self.to_check['CalculationNode'][1]).with_entities('dbnode_id').one()[0]
                self.assertEqual(dbnode_id_1, self.to_check['CalculationNode'][0], "The the referenced node is not "
                                 "the expected one")
                dbnode_id_2 = session.query(DbLog).filter(
                    DbLog.id == self.to_check['CalculationNode'][3]).with_entities('dbnode_id').one()[0]
                self.assertEqual(dbnode_id_2, self.to_check['CalculationNode'][2], "The the referenced node is not "
                                 "the expected one")
            finally:
                session.close()

    def test_dblog_correct_export_of_logs(self):
        """
        Verify that export log methods for legacy workflows and unknown entities work as expected
        """
        self.assertEqual(self.to_check['ParameterData'][0], self.to_check['ParameterData'][1])
        self.assertEqual(self.to_check['ParameterData'][2], 1)

        self.assertEqual(self.to_check['WorkflowNode'][0], self.to_check['WorkflowNode'][1])
        self.assertEqual(self.to_check['WorkflowNode'][2], 1)

    def test_metadata_correctness(self):
        """
        Verify that the metadata of the remaining records don't have an objpk and objmetadata values.
        """
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        DbLog = self.get_auto_base().classes.db_dblog  # pylint: disable=invalid-name

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)
                metadata = list(session.query(DbLog).with_entities(getattr(DbLog, 'metadata')).all())
                # Verify that the objpk and objname are no longer part of the metadata
                for (m_res,) in metadata:
                    self.assertNotIn('objpk', m_res.keys(), "objpk should not exist any more in metadata")
                    self.assertNotIn('objname', m_res.keys(), "objname should not exist any more in metadata")

            finally:
                session.close()


class TestDbLogMigrationBackward(TestBackwardMigrationsSQLA):
    """
    Check that backward migrations work also for the DbLog migration(s).
    """
    migrate_from = '041a79fc615f'  # 041a79fc615f_dblog_cleaning
    migrate_to = '7ca08c391c49'  # e72ad251bcdb_dbgroup_class_change_type_string_values

    def setUpBeforeMigration(self):
        # pylint: disable=too-many-locals,too-many-statements
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        DbUser = self.get_auto_base().classes.db_dbuser  # pylint: disable=invalid-name
        DbNode = self.get_auto_base().classes.db_dbnode  # pylint: disable=invalid-name
        DbLog = self.get_auto_base().classes.db_dblog  # pylint: disable=invalid-name

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)

                user = DbUser(is_superuser=False, email="{}@aiida.net".format(self.id()))
                session.add(user)
                session.commit()

                calc_1 = DbNode(type="node.process.calculation.CalculationNode.1", user_id=user.id)
                calc_2 = DbNode(type="node.process.calculation.CalculationNode.2", user_id=user.id)

                session.add(calc_1)
                session.add(calc_2)
                session.commit()

                log_1 = DbLog(
                    loggername='CalculationNode logger',
                    dbnode_id=calc_1.id,
                    message='calculation node 1',
                    metadata={
                        "msecs": 719.0849781036377,
                        "lineno": 350,
                        "thread": 140011612940032,
                        "asctime": "10/21/2018 12:39:51 PM",
                        "created": 1540118391.719085,
                        "levelno": 23,
                        "message": "calculation node 1",
                    })
                log_2 = DbLog(
                    loggername='CalculationNode logger',
                    dbnode_id=calc_2.id,
                    message='calculation node 2',
                    metadata={
                        "msecs": 719.0849781036377,
                        "lineno": 360,
                        "levelno": 23,
                        "message": "calculation node 1",
                    })

                session.add(log_1)
                session.add(log_2)

                session.commit()

                # Keeping what is needed to be verified at the test
                self.to_check = dict()
                self.to_check[log_1.id] = (log_1.dbnode_id, calc_1.type)
                self.to_check[log_2.id] = (log_2.dbnode_id, calc_2.type)
            except:
                session.rollback()
                raise
            finally:
                session.close()

    def test_objpk_objname(self):
        """
        This test verifies that the objpk and objname have the right values
        after a forward and a backward migration.
        """
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        DbLog = self.get_auto_base().classes.db_dblog  # pylint: disable=invalid-name

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)

                for log_pk in self.to_check:
                    log_entry = session.query(DbLog).filter(DbLog.id == log_pk).one()
                    log_dbnode_id, node_type = self.to_check[log_pk]

                    self.assertEqual(
                        log_dbnode_id, log_entry.objpk,
                        "The dbnode_id ({}) of the 0024 schema version should be identical to the objpk ({}) of "
                        "the 0023 schema version.".format(log_dbnode_id, log_entry.objpk))
                    self.assertEqual(
                        node_type, log_entry.objname,
                        "The type ({}) of the linked node of the 0024 schema version should be identical to the "
                        "objname ({}) of the 0023 schema version.".format(node_type, log_entry.objname))
                    self.assertEqual(
                        log_dbnode_id, log_entry.metadata['objpk'],
                        "The dbnode_id ({}) of the 0024 schema version should be identical to the objpk ({}) of "
                        "the 0023 schema version stored in the metadata.".format(log_dbnode_id,
                                                                                 log_entry.metadata['objpk']))
                    self.assertEqual(
                        node_type, log_entry.metadata['objname'],
                        "The type ({}) of the linked node of the 0024 schema version should be identical to the "
                        "objname ({}) of the 0023 schema version stored in the metadata.".format(
                            node_type, log_entry.metadata['objname']))
            finally:
                session.close()


class TestDbLogUUIDAddition(TestMigrationsSQLA):
    """
    Test that the UUID column is correctly added to the DbLog table and that the uniqueness
    constraint is added without problems (if the migration arrives until 375c2db70663 then the
    constraint is added properly.
    """

    migrate_from = '041a79fc615f'  # 041a79fc615f_dblog_cleaning
    migrate_to = '375c2db70663'  # 375c2db70663_dblog_uuid_uniqueness_constraint

    def setUpBeforeMigration(self):
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        DbUser = self.get_auto_base().classes.db_dbuser  # pylint: disable=invalid-name
        DbNode = self.get_auto_base().classes.db_dbnode  # pylint: disable=invalid-name
        DbLog = self.get_auto_base().classes.db_dblog  # pylint: disable=invalid-name

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)

                user = DbUser(is_superuser=False, email="{}@aiida.net".format(self.id()))
                session.add(user)
                session.commit()

                calc_1 = DbNode(type="node.process.calculation.CalculationNode.", user_id=user.id)
                calc_2 = DbNode(type="node.process.calculation.CalculationNode.", user_id=user.id)

                session.add(calc_1)
                session.add(calc_2)
                session.commit()

                log_1 = DbLog(loggername='CalculationNode logger', dbnode_id=calc_1.id, message='calculation node 1')
                log_2 = DbLog(loggername='CalculationNode logger', dbnode_id=calc_2.id, message='calculation node 2')

                session.add(log_1)
                session.add(log_2)

                session.commit()
            except:
                session.rollback()
                raise
            finally:
                session.close()

    def test_dblog_unique_uuids(self):
        """
        Verify that the UUIDs of the log records are unique
        """
        from sqlalchemy.orm import Session  # pylint: disable=import-error,no-name-in-module

        DbLog = self.get_auto_base().classes.db_dblog  # pylint: disable=invalid-name

        with sa.engine.begin() as connection:
            try:
                session = Session(connection.engine)
                l_uuids = list(session.query(DbLog).with_entities(getattr(DbLog, 'uuid')).all())
                s_uuids = set(l_uuids)
                self.assertEqual(len(l_uuids), len(s_uuids), "The UUIDs are not all unique.")
            finally:
                session.close()
