# -*- coding: utf-8 -*-

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestClinicManagement(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Patient = cls.env["gl.clinic.patient"]
        cls.History = cls.env["gl.clinic.medical.history"]
        cls.doctor_user = cls.env["res.users"].create({
            "name": "Médico de prueba",
            "login": "doctor_prueba",
            "email": "doctor@example.com",
            "groups_id": [(6, 0, [cls.env.ref("gl_clinic_management.group_gl_clinic_doctor").id])],
        })
        cls.patient = cls.Patient.create({
            "first_name": "Juan",
            "last_name": "Pérez",
            "document_number": "12345678",
            "birth_date": date(1990, 1, 1),
        })

    def _create_history(self, patient=None, user=None):
        History = self.History.with_user(user) if user else self.History
        doctor = user or self.env.user
        return History.create({
            "patient_id": (patient or self.patient).id,
            "attention_date": "2026-07-31 10:00:00",
            "doctor_id": doctor.id,
            "height": 1.70,
            "weight": 70.0,
            "diagnosis": "Contusión leve",
        })

    def test_patient_creation_and_age(self):
        self.assertTrue(self.patient.internal_number)
        self.assertEqual(self.patient.full_name, "Juan Pérez")
        self.assertGreaterEqual(self.patient.age, 36)

    def test_unique_document_by_company(self):
        with self.assertRaises(Exception):
            self.Patient.create({
                "first_name": "Juan",
                "last_name": "Duplicado",
                "document_number": "12345678",
            })

    def test_birth_date_validation(self):
        with self.assertRaises(ValidationError):
            self.Patient.create({
                "first_name": "Futuro",
                "last_name": "Paciente",
                "document_number": "87654321",
                "birth_date": date(2999, 1, 1),
            })

    def test_history_sequence_and_bmi(self):
        history = self._create_history()
        self.assertTrue(history.name.startswith("HC-"))
        self.assertAlmostEqual(history.bmi, 24.22, places=2)
        self.assertEqual(history.bmi_classification, "Normal")

    def test_confirm_restricts_write_and_unlink(self):
        history = self._create_history(user=self.doctor_user)
        history.action_confirm()
        self.assertEqual(history.state, "confirmed")
        self.assertTrue(history.confirmed_by_id)
        with self.assertRaises(UserError):
            history.with_user(self.doctor_user).write({"diagnosis": "Cambio"})
        with self.assertRaises(UserError):
            history.with_user(self.doctor_user).unlink()

    def test_neighbor_navigation(self):
        first = self._create_history()
        second = self.History.create({
            "patient_id": self.patient.id,
            "attention_date": "2026-08-01 10:00:00",
            "doctor_id": self.env.user.id,
            "height": 1.70,
            "weight": 70.0,
        })
        action = first.action_next_history()
        self.assertEqual(action["res_id"], second.id)

    def test_company_separation_document(self):
        other_company = self.env["res.company"].create({"name": "Otra empresa"})
        patient = self.Patient.with_company(other_company).create({
            "first_name": "Juan",
            "last_name": "Otra empresa",
            "document_number": "12345678",
            "company_id": other_company.id,
        })
        self.assertEqual(patient.company_id, other_company)
